#!/usr/bin/env node
/**
 * Build-time guard: chart components must receive an explicit ticker/symbol.
 * Fails CI on silent AAPL/SPY/BTC defaults or missing required instrument props.
 */
const fs = require("fs");
const path = require("path");

const FRONTEND_SRC = path.join(__dirname, "..", "src");
const SCAN_ROOTS = [
  path.join(FRONTEND_SRC, "components"),
  path.join(FRONTEND_SRC, "app"),
];

const CHART_TAGS = [
  "LightweightChart",
  "PriceChart",
  "AssetCockpitChart",
  "GridChart",
  "TerminalChart",
];

const HARDCODED_FALLBACK = /(\|\|\s*["'](AAPL|SPY|BTC|BTCUSDT|BTC\/USDT)["']|DEFAULT_CHART_SYMBOL\b|useState\s*\(\s*["'](AAPL|SPY|BTC)["'])/;
const OPEN_TAG = new RegExp(`<(${CHART_TAGS.join("|")})\\b([^>]*)>`, "g");

function collectFiles(root) {
  const out = [];
  if (!fs.existsSync(root)) return out;
  const st = fs.statSync(root);
  if (st.isFile()) {
    if (/\.(tsx|jsx)$/.test(root)) out.push(root);
    return out;
  }
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === "__tests__") continue;
    out.push(...collectFiles(path.join(root, entry.name)));
  }
  return out;
}

const violations = [];
for (const root of SCAN_ROOTS) {
  for (const file of collectFiles(root)) {
    const rel = path.relative(FRONTEND_SRC, file).split(path.sep).join("/");
    const text = fs.readFileSync(file, "utf8");
    const lines = text.split(/\r?\n/);
    lines.forEach((line, i) => {
      if (HARDCODED_FALLBACK.test(line) && !/check-chart-symbol|chartSymbol\.test/.test(rel)) {
        violations.push(`${rel}:${i + 1}: hardcoded chart fallback — ${line.trim().slice(0, 120)}`);
      }
    });
    let m;
    const re = new RegExp(OPEN_TAG.source, "g");
    while ((m = re.exec(text)) !== null) {
      const attrs = m[2] || "";
      const hasInstrument = /\b(ticker|symbol)\s*=/.test(attrs);
      if (!hasInstrument && !attrs.includes("...")) {
        const lineNo = text.slice(0, m.index).split(/\r?\n/).length;
        violations.push(`${rel}:${lineNo}: <${m[1]}> missing explicit ticker/symbol prop`);
      }
    }
  }
}

if (violations.length) {
  console.error(`Chart symbol required-prop violations (${violations.length}):\n`);
  violations.forEach((v) => console.error(`  ${v}`));
  process.exit(1);
}
console.log("Chart components: required symbol prop / no silent ticker defaults OK");
