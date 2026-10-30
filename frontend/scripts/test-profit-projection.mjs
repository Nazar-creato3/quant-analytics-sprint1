import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const sourcePath = path.join(root, "src", "lib", "profit-projection.ts");
const source = await readFile(sourcePath, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2020,
    target: ts.ScriptTarget.ES2020,
  },
});

const tempDir = await mkdtemp(path.join(tmpdir(), "apex-profit-projection-"));
try {
  const modulePath = path.join(tempDir, "profit-projection.mjs");
  await writeFile(modulePath, compiled.outputText, "utf8");
  const {
    computeRemainingTime,
    formatExpiryCountdown,
    formatUsdPnl,
    monotonicCountdownSeconds,
    remainingSecondsFromExpiry,
  } = await import(pathToFileURL(modulePath).href);

  assert.equal(formatUsdPnl(-0.44), "−$0.44");
  assert.equal(formatUsdPnl(0.35), "+$0.35");
  assert.equal(formatUsdPnl(0), "$0");

  assert.equal(formatExpiryCountdown(59), "00:00:59");
  assert.equal(formatExpiryCountdown(60), "00:01:00");
  assert.equal(formatExpiryCountdown(61), "00:01:01");
  assert.equal(formatExpiryCountdown(3_540), "00:59:00");
  assert.equal(formatExpiryCountdown(3_599), "00:59:59");
  assert.equal(formatExpiryCountdown(93_660), "1d 02:01:00");
  assert.equal(formatExpiryCountdown(302_400), "3d 12:00:00");
  assert.equal(formatExpiryCountdown(0), "срок вышел");

  const now = Date.parse("2026-08-03T12:00:00.000Z");
  assert.equal(computeRemainingTime("2026-08-03T12:10:00.000Z", now), 600);
  assert.equal(computeRemainingTime("2026-08-03T12:00:01.000Z", now), 1);
  assert.equal(computeRemainingTime("2026-08-03T11:59:59.000Z", now), 0);
  assert.equal(computeRemainingTime("2026-08-04T00:00:30.000Z", Date.parse("2026-08-03T23:59:30.000Z")), 60);
  assert.equal(computeRemainingTime(null, now), null);

  const serverNowIso = "2026-08-03T12:00:00.000Z";
  const expiresAtIso = "2026-08-03T12:05:00.000Z";
  const fetchedAt = Date.parse("2026-08-03T15:00:00.000Z"); // client clock is +3h
  const visibleAtStart = formatExpiryCountdown(
    remainingSecondsFromExpiry(expiresAtIso, serverNowIso, fetchedAt, fetchedAt),
  );
  const visibleAfterTwoMinutes = formatExpiryCountdown(
    remainingSecondsFromExpiry(expiresAtIso, serverNowIso, fetchedAt + 120_000, fetchedAt),
  );
  assert.equal(visibleAtStart, "00:05:00");
  assert.equal(visibleAfterTwoMinutes, "00:03:00");

  const previous = 180;
  const skewBumped = 184;
  assert.equal(monotonicCountdownSeconds(skewBumped, previous), previous);
  assert.equal(monotonicCountdownSeconds(179, previous), 179);
} finally {
  await rm(tempDir, { recursive: true, force: true });
}

