#!/usr/bin/env node
/**
 * Pre-commit guard: flag hardcoded #hex / rgba() in frontend/src outside chartColors.ts.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "src");
const ALLOWED_SUFFIX = `${path.sep}lib${path.sep}chartColors.ts`;
const HEX = /#[0-9a-fA-F]{3,8}\b/;
const RGBA = /rgba?\(\s*\d+/;

const violations = [];

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full);
      continue;
    }
    if (!/\.(tsx?|jsx?)$/.test(entry.name)) continue;
    const rel = path.relative(ROOT, full).split(path.sep).join("/");
    if (full.endsWith(ALLOWED_SUFFIX) || full.includes(`${path.sep}lib${path.sep}chartColors.ts`)) continue;

    const text = fs.readFileSync(full, "utf8");
    const lines = text.split(/\r?\n/);
    lines.forEach((line, index) => {
      if (HEX.test(line) || RGBA.test(line)) {
        violations.push(`${rel}:${index + 1}: ${line.trim().slice(0, 120)}`);
      }
    });
  }
}

walk(ROOT);

if (violations.length) {
  console.error("Hardcoded color literals found (use design tokens or chartColors.ts):\n");
  violations.forEach((v) => console.error(`  ${v}`));
  process.exit(1);
}

console.log("No hardcoded color violations outside chartColors.ts");
