import { describe, expect, it } from "vitest";
import { HOME_USER_COPY } from "@/app/homeUserCopy";
import { PAGE_ERROR_COPY } from "@/components/layout/PageErrorBoundary";

describe("home and page-error copy (AUD-K-05)", () => {
  it("does not show Dashboard, LIVE, Retry, or dashboard to the user", () => {
    expect(HOME_USER_COPY.errorTitle).toBe("Главная");
    expect(HOME_USER_COPY.liveBanner).toBe("Боевой режим");
    expect(PAGE_ERROR_COPY.retry).toBe("Обновить");
    expect(PAGE_ERROR_COPY.body).toContain("главную");
    const blob = `${HOME_USER_COPY.errorTitle} ${HOME_USER_COPY.liveBanner} ${PAGE_ERROR_COPY.body} ${PAGE_ERROR_COPY.retry}`;
    expect(blob).not.toMatch(/Dashboard|LIVE|Retry|dashboard/);
  });
});
