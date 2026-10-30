import { expect, test } from "@playwright/test";

test("login screen is reachable (journey register/login scaffold)", async ({
  page,
}) => {
  await page.goto("/login");
  await expect(page.getByText(/Quant Analytics|Вход/i).first()).toBeVisible();
  await expect(page.locator('input[type="email"], input[name="email"]').first()).toBeVisible();
});

test("login submit shows rejected credentials from API", async ({ page }) => {
  await page.route("**/auth/login", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Invalid credentials" }),
    });
  });
  await page.goto("/login");
  await page.locator('input[type="email"]').first().fill("qa@example.com");
  await page.locator('input[type="password"]').first().fill("wrong-password");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByText(/Invalid credentials|неверн|ошибк/i).first()).toBeVisible({
    timeout: 15_000,
  });
});
