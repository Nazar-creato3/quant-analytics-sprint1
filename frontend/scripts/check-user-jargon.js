#!/usr/bin/env node
/**
 * CI guard category (b): internal jargon reaching end users.
 * Flags snake_case identifiers and known provider/model keys in JSX/user strings.
 * Admin-only paths are excluded.
 */
const fs = require("fs");
const path = require("path");

const FRONTEND_SRC = path.join(__dirname, "..", "src");
const SCAN_ROOTS = [
  path.join(FRONTEND_SRC, "app"),
  path.join(FRONTEND_SRC, "components"),
];

const SKIP_DIR_PARTS = [
  "admin",
  "operator",
  "ops",
  "__tests__",
  "node_modules",
];
const SKIP_FILES = new Set([
  path.normalize(path.join(FRONTEND_SRC, "lib", "user-facing-labels.ts")),
  path.normalize(path.join(FRONTEND_SRC, "lib", "ui-i18n.ts")),
]);

const SNAKE_IN_JSX = />\s*([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*</;
const SNAKE_IN_ATTR =
  /\b(title|placeholder|aria-label|label|subtitle|description)\s*=\s*["']([a-z][a-z0-9]*(?:_[a-z0-9]+)+)["']/;
const PROVIDER_KEYS =
  /\b(alpaca_nbbo_iex|alpaca_nbbo|chronos_t5_tiny|regime_match_accuracy|aggregate_calibration_error|direction_accuracy|direction_lgbm|marketstack|EOD)\b/;
const RAW_DYNAMIC_DISPLAY =
  /^\s*\{[^}]*\.(source|provider|engine|status|strategy|risk_tag|approval_state)[^}]*\}\s*$/;
const UNDERSCORE_FALLBACK = /\.replace\(\s*\/_\/g\s*,\s*["'] ["']\s*\)/;
const PROVIDER_IN_STRING =
  /(["'`])[^"'`]*\b(alpaca_nbbo_iex|alpaca_nbbo|chronos_t5_tiny|regime_match_accuracy|aggregate_calibration_error|direction_accuracy|direction_lgbm|marketstack|EOD)\b[^"'`]*\1/;

const ALLOW_LINE = [
  /ui\s*\(/,
  /uiFmt\s*\(/,
  /label(Source|Metric|Model|Engine|OrderStatus|Technical|Action|Regime|RiskFlag)\s*\(/,
  /sanitizeUserText\s*\(/,
  /[A-Z0-9_]+LABELS\s*\[/,
  /^\s*import\s/,
  /console\./,
  /\/\//,
  /\/\*/,
  /const\s+[A-Z0-9_]+\s*=/,
];

function collectFiles(root) {
  const out = [];
  if (!fs.existsSync(root)) return out;
  const st = fs.statSync(root);
  if (st.isFile()) {
    if (/\.(tsx|jsx)$/.test(root) && !SKIP_FILES.has(path.normalize(root))) out.push(root);
    return out;
  }
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (SKIP_DIR_PARTS.some((p) => entry.name === p)) continue;
    out.push(...collectFiles(path.join(root, entry.name)));
  }
  return out;
}

const violations = [];
for (const root of SCAN_ROOTS) {
  for (const file of collectFiles(root)) {
    const rel = path.relative(FRONTEND_SRC, file).split(path.sep).join("/");
    const lines = fs.readFileSync(file, "utf8").split(/\r?\n/);
    lines.forEach((line, i) => {
      if (ALLOW_LINE.some((re) => re.test(line))) return;
      if (
        SNAKE_IN_JSX.test(line) ||
        SNAKE_IN_ATTR.test(line) ||
        (PROVIDER_KEYS.test(line) && PROVIDER_IN_STRING.test(line)) ||
        RAW_DYNAMIC_DISPLAY.test(line) ||
        UNDERSCORE_FALLBACK.test(line)
      ) {
        if (
          PROVIDER_IN_STRING.test(line) ||
          SNAKE_IN_JSX.test(line) ||
          SNAKE_IN_ATTR.test(line) ||
          RAW_DYNAMIC_DISPLAY.test(line) ||
          UNDERSCORE_FALLBACK.test(line)
        ) {
          violations.push(`${rel}:${i + 1}: ${line.trim().slice(0, 140)}`);
        }
      }
    });
  }
}

if (violations.length) {
  console.error(`User-facing jargon violations (${violations.length}):\n`);
  violations.forEach((v) => console.error(`  ${v}`));
  process.exit(1);
}
console.log("No user-facing jargon violations in scanned UI scope");
