#!/usr/bin/env node
/**
 * CI guard: flag hardcoded user-visible English strings in terminal UI.
 * Strings must go through ui() / uiFmt() from src/lib/ui-i18n.ts.
 * Category (a) — English where Russian is expected.
 * Category (b) is scripts/check-user-jargon.js (separate).
 */
const fs = require("fs");
const path = require("path");

const FRONTEND_SRC = path.join(__dirname, "..", "src");
const SCAN_ROOTS = [
  path.join(FRONTEND_SRC, "components", "terminal"),
  path.join(FRONTEND_SRC, "components", "charts", "LightweightChart.tsx"),
  path.join(FRONTEND_SRC, "components", "orders"),
  path.join(FRONTEND_SRC, "components", "direct-deals"),
  path.join(FRONTEND_SRC, "components", "search"),
  path.join(FRONTEND_SRC, "components", "mobile"),
];

const SKIP_FILES = new Set([
  path.normalize(path.join(FRONTEND_SRC, "lib", "ui-i18n.ts")),
  path.normalize(path.join(FRONTEND_SRC, "lib", "duration-i18n.ts")),
]);

const JSX_ATTR =
  /\b(title|placeholder|aria-label|alt|description|subtitle|text|label)\s*=\s*["']([^"']+)["']/;

const LABEL_PROP = /\blabel\s*:\s*["']([^"']+)["']/;

const JSX_TEXT = />\s*([A-Za-z][A-Za-z0-9\s&'.,!?/—–-]{2,})\s*</;

const ALLOW_LINE = [
  /ui\s*\(/,
  /uiFmt\s*\(/,
  /uiFearGreedLabel\s*\(/,
  /uiVolRegime\s*\(/,
  /^\s*import\s/,
  /^\s*export\s/,
  /className=/,
  /\bkey=/,
  /\bhref=/,
  /\btype=/,
  /\brole=/,
  /aria-hidden/,
  /\bdata-/,
  /console\./,
  /\/\//,
  /\/\*/,
  /^\s*\*/,
  /fetch-depth/,
  /grid-cols-/,
  /viewBox/,
  /preserveAspectRatio/,
  /LineStyle\./,
  /ISeriesApi/,
  /chartColors\./,
  /var\(--/,
  /http/,
  /\.(tsx?|jsx?|css|ps1)/,
  /github\.com/,
  /^\s*\/\\/,
];

const ALLOW_STRING = [
  /^—$/,
  /^MSK$/,
  /^API$/,
  /^Esc$/,
  /^VaR$/,
  /^H$/,
  /^L$/,
  /^M$/,
  /^OPEN$/,
  /^CLOSED$/,
  /^PRE$/,
  /^POST$/,
  /^HOLIDAY$/,
  /^HOL$/,
  /^compact$/,
  /^comfortable$/,
  /^live$/,
  /^partial$/,
  /^mock$/,
  /^terminal$/,
  /^default$/,
  /^portfolio$/,
  /^positions$/,
  /^up$/,
  /^down$/,
  /^neutral$/,
  /^long$/,
  /^short$/,
  /^approve$/,
  /^reject$/,
  /^pong$/,
  /^ping$/,
  /^Action$/,
  /^[A-Z0-9/._^=-]{1,8}$/,
  /^\d/,
  /^[\u0400-\u04FF]/,
];

function hasCyrillic(s) {
  return /[\u0400-\u04FF]/.test(s);
}

function isAllowedString(s) {
  const t = s.trim();
  if (!t || t.length < 2) return true;
  if (hasCyrillic(t)) return true;
  return ALLOW_STRING.some((re) => re.test(t));
}

function collectFiles(root) {
  const out = [];
  if (!fs.existsSync(root)) return out;
  const stat = fs.statSync(root);
  if (stat.isFile()) {
    if (/\.(tsx?|jsx?)$/.test(root) && !SKIP_FILES.has(path.normalize(root))) {
      out.push(root);
    }
    return out;
  }
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.name === "__tests__" || entry.name.endsWith(".test.tsx") || entry.name.endsWith(".test.ts")) {
      continue;
    }
    out.push(...collectFiles(path.join(root, entry.name)));
  }
  return out;
}

const violations = [];

for (const root of SCAN_ROOTS) {
  for (const file of collectFiles(root)) {
    const rel = path.relative(FRONTEND_SRC, file).split(path.sep).join("/");
    const lines = fs.readFileSync(file, "utf8").split(/\r?\n/);
    lines.forEach((line, index) => {
      if (ALLOW_LINE.some((re) => re.test(line))) return;

      const checks = [];
      const attr = line.match(JSX_ATTR);
      if (attr) checks.push(attr[2]);
      const label = line.match(LABEL_PROP);
      if (label) checks.push(label[1]);
      const text = line.match(JSX_TEXT);
      if (text) checks.push(text[1].trim());

      for (const raw of checks) {
        if (isAllowedString(raw)) continue;
        if (/^[A-Za-z]/.test(raw) && raw.length >= 3) {
          violations.push(`${rel}:${index + 1}: ${line.trim().slice(0, 140)}`);
          break;
        }
      }
    });
  }
}

if (violations.length) {
  console.error(`Hardcoded i18n violations (${violations.length}) — use ui() from ui-i18n.ts:\n`);
  violations.forEach((v) => console.error(`  ${v}`));
  process.exit(1);
}

console.log("No hardcoded i18n violations in terminal UI scope");
