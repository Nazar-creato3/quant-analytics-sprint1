import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

export const CYCLE_PAGES = [
  { id: "learn", href: "/markets", cycle: "learn" },
  { id: "evaluate", href: "/forecasting", cycle: "evaluate" },
  { id: "risk", href: "/portfolio-report", cycle: "risk" },
  { id: "act", href: "/direct-deals", cycle: "act" },
  { id: "control", href: "/account", cycle: "control" },
] as const;

const E2E_USER = {
  id: "e2e-user",
  email: "e2e@example.com",
  role: "analyst",
  is_active: true,
  is_whitelisted: true,
  created_at: "2026-01-01T00:00:00Z",
  last_login: "2026-10-04T00:00:00Z",
};

export async function stubApis(page: Page): Promise<void> {
  await page.route("**/*", async (route) => {
    const url = route.request().url();
    const isApi = url.includes("/api/v1/") || url.includes("/api/");
    if (!isApi) {
      await route.continue();
      return;
    }
    if (url.includes("/auth/me")) {
      await route.fulfill({ json: E2E_USER });
      return;
    }
    if (url.includes("/auth/csrf-token")) {
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/json",
          "set-cookie": "apex_csrf=e2e-csrf; Path=/",
        },
        json: { csrf_token: "e2e-csrf" },
      });
      return;
    }
    if (url.includes("/access") || url.includes("/policy")) {
      await route.fulfill({
        json: {
          access_level: "paper",
          paid: true,
          show_trial_timer: false,
          account_nav_locked: false,
        },
      });
      return;
    }
    if (url.includes("/regime")) {
      await route.fulfill({
        json: {
          market: { ticker: "IMOEX", label: "range", explain: "e2e", scope: "market" },
          instrument: null,
        },
      });
      return;
    }
    if (url.includes("/onboarding/demo") || url.includes("/onboarding/start")) {
      await route.fulfill({
        json: {
          user_id: "e2e-user",
          path: "try_demo",
          ready_report: true,
          next: "/portfolio-report",
          mode: "paper",
          stages: ["accounts", "positions", "history", "prices", "calc"],
          stages_done: ["accounts", "positions", "history", "prices", "calc"],
        },
      });
      return;
    }
    if (url.includes("/onboarding")) {
      await route.fulfill({
        json: { empty: true, paths: ["have_account", "partner", "try_demo"] },
      });
      return;
    }
    if (url.includes("/report")) {
      await route.fulfill({
        json: {
          headline: "E2E",
          demo: true,
          empty: true,
          disclaimer: "демо",
          elapsed_ms: 1,
          first_screen: { twr: null, mwr: null, hhi: null, data_status: "нет данных" },
          queues: { q4_unrated_bonds: { status: "beta" } },
          stress: { scenarios: [] },
          changed: [],
        },
      });
      return;
    }
    if (url.includes("/stress-library")) {
      await route.fulfill({ json: { disclaimer: "e2e", empty: true, scenarios: [] } });
      return;
    }
    if (url.includes("/concentration")) {
      await route.fulfill({ json: { empty: true } });
      return;
    }
    if (url.includes("/behavior")) {
      await route.fulfill({ json: { insufficient: true, text: "мало сделок", sample_size: 0 } });
      return;
    }
    if (url.includes("/notifications")) {
      await route.fulfill({
        json: {
          items: [{ id: 1, event_name: "account.sync_failed", text: "Синхронизация счёта tbank не удалась. Статус: ошибка.", href: "/portfolio-report" }],
          count: 1,
        },
      });
      return;
    }
    if (url.includes("/qa-tools")) {
      await route.fulfill({
        json: { items: [{ label: "Риск", href: "/portfolio-risk" }], tools: [{ name: "qa_portfolio_report" }] },
      });
      return;
    }
    if (url.includes("/sandbox") || url.includes("/personal-limits") || url.includes("/instrument-calendar") || url.includes("/digest")) {
      await route.fulfill({ status: 404, json: { detail: "flag off" } });
      return;
    }
    if (url.includes("/act/")) {
      await route.fulfill({
        json: {
          items: [],
          empty: true,
          reason: "e2e",
          note: "e2e",
          delta: {
            hhi: { before: "0", after: "0" },
            var_95: { before: "0", after: "0" },
          },
        },
      });
      return;
    }
    if (url.includes("/investment-profile")) {
      await route.fulfill({
        json: {
          empty: true,
          data_status: "нет данных",
          version: 1,
          limits: { var_95: "0.050", es_975: "0.070", max_drawdown: "0.150" },
          warnings: [],
        },
      });
      return;
    }
    if (url.includes("/forecast-core")) {
      await route.fulfill({
        json: {
          ticker: "SBER",
          direction: 1,
          probability: 0.5,
          trust: "low",
          horizon_enabled: true,
          horizon_reason: "e2e",
          degraded_note: "",
        },
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"items":[]}' });
  });
}

/** Propose response that already used the saved profile (has the user book). */
export function waitForLivePropose(page: Page): Promise<import("@playwright/test").Response> {
  return page.waitForResponse(async (response) => {
    if (!response.url().includes("/api/v1/act/propose") || response.request().method() !== "POST" || !response.ok()) {
      return false;
    }
    try {
      const body = await response.json();
      return body?.target_source === "user" && String(body?.target_book?.tax?.rate || "").includes("2400000");
    } catch {
      return false;
    }
  }, { timeout: 120_000 });
}

/** Fill the live questionnaire and wait for the real POST. */
export async function saveLiveProfile(page: Page): Promise<import("@playwright/test").Response> {
  await expect(page.getByTestId("investment-profile")).toBeVisible({ timeout: 90_000 });
  await page.locator("#age").fill("40");
  await page.locator("#income_12m").fill("100000");
  await page.locator("#expenses_12m").fill("50000");
  await page.locator("#savings").fill("200000");
  await page.locator("#education").fill("высшее");
  await expect(page.locator("#age")).toHaveValue("40");
  const saved = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/investment-profile") && response.request().method() === "POST",
    { timeout: 120_000 },
  );
  await page.getByTestId("profile-save").click();
  return saved;
}

/** Real register + JWT. Does not stub /api. The user row is in PostgreSQL. */
export async function openLive(page: Page, path: string): Promise<void> {
  const api = process.env.E2E_API_URL || "http://127.0.0.1:8000";
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  const password = `Base${Date.now()}aA1`;
  const reg = await page.request.post(`${api}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 120_000,
  });
  const raw = await reg.text();
  if (!reg.ok()) {
    throw new Error(`register ${reg.status()} ${raw}`);
  }
  const body = JSON.parse(raw) as { access_token?: string };
  const token = body.access_token || "";
  if (!token) {
    throw new Error(`register returned no access_token ${raw}`);
  }
  const part = token.split(".")[1] || "";
  const payload = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as { user_id?: string };
  const userId = String(payload.user_id || "");
  if (!userId) {
    throw new Error("access token has no user_id");
  }
  const origin =
    process.env.E2E_BASE_URL || `http://127.0.0.1:${process.env.E2E_PORT || "3000"}`;
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript(
    ({ liveToken, liveUser }) => {
      localStorage.setItem("access_token", liveToken);
      localStorage.setItem("qa.activeAccount", liveUser);
      localStorage.setItem("qa.bookMode", "paper");
    },
    { liveToken: token, liveUser: userId },
  );
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("paper-live-badge")).toBeVisible({ timeout: 60_000 });
}

export async function openAuthed(page: Page, path: string): Promise<void> {
  const origin = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
  await page.context().addCookies([{ name: "access_token", value: "e2e-shell", url: origin }]);
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "e2e-shell");
    localStorage.setItem("refresh_token", "e2e-refresh");
    if (!localStorage.getItem("qa.bookMode")) {
      localStorage.setItem("qa.bookMode", "paper");
    }
  });
  await stubApis(page);
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("paper-live-badge")).toBeVisible({ timeout: 20_000 });
}

export async function assertNoSeriousAxe(page: Page, name: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const blocking = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  const detail = blocking
    .map((v) => `${v.id} [${v.impact}] ${v.help}: ${v.nodes.map((n) => n.target.join(" ")).join("; ")}`)
    .join("\n");
  expect(blocking, `${name}\n${detail}`).toEqual([]);
}

export async function snapCyclePage(page: Page, id: string): Promise<void> {
  const dir = resolve(process.cwd(), "../docs/qa/reports/18-screenshots");
  mkdirSync(dir, { recursive: true });
  const file = resolve(dir, `${id}.png`);
  const buf = await page.screenshot({ path: file, fullPage: false, animations: "disabled" });
  expect(buf.byteLength, `${id} screenshot too small`).toBeGreaterThan(4_000);
}
