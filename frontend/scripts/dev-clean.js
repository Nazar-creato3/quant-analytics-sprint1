#!/usr/bin/env node
/**
 * Kill stale Next.js on port 3000, remove .next cache, start `next dev`.
 * Use when the page renders unstyled (CSS chunks 404) after hot reload or crash.
 */
const { execSync, spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const PORT = process.env.PORT || 3000;
const frontendRoot = path.join(__dirname, "..");

function killPort(port) {
  try {
    if (process.platform === "win32") {
      const out = execSync(`netstat -ano | findstr :${port}`, {
        encoding: "utf8",
        stdio: ["pipe", "pipe", "ignore"],
      });
      const pids = new Set();
      for (const line of out.split("\n")) {
        const m = line.match(/\s+(\d+)\s*$/);
        if (m && m[1] !== "0") pids.add(m[1]);
      }
      for (const pid of pids) {
        try {
          execSync(`taskkill /F /PID ${pid}`, { stdio: "ignore" });
          console.log(`Stopped process ${pid} on port ${port}`);
        } catch {
          /* already gone */
        }
      }
    } else {
      execSync(`lsof -ti:${port} | xargs kill -9 2>/dev/null || true`, {
        shell: true,
        stdio: "ignore",
      });
    }
  } catch {
    /* nothing listening */
  }
}

killPort(PORT);

const nextDir = path.join(frontendRoot, ".next");

function removeNextDir(dir) {
  if (!fs.existsSync(dir)) return;

  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      fs.rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
      console.log("Removed .next cache");
      return;
    } catch (err) {
      if (attempt === 5 && process.platform === "win32") {
        try {
          execSync(`rmdir /s /q "${dir}"`, { stdio: "ignore" });
          console.log("Removed .next cache (rmdir fallback)");
          return;
        } catch {
          /* fall through */
        }
      }
      if (attempt < 5) {
        execSync(process.platform === "win32" ? "timeout /t 1 /nobreak >nul" : "sleep 1", {
          shell: true,
          stdio: "ignore",
        });
        continue;
      }
      throw err;
    }
  }
}

removeNextDir(nextDir);

const child = spawn("npx", ["next", "dev"], {
  cwd: frontendRoot,
  stdio: "inherit",
  shell: true,
});

child.on("exit", (code) => process.exit(code ?? 0));
