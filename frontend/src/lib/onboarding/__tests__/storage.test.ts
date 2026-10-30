import { afterEach, describe, expect, it } from "vitest";
import {
  completeOnboarding,
  hasOnboardingOffer,
  isOnboardingDone,
  markOnboardingOffer,
  shouldAutoStartOnboarding,
} from "../storage";
import { stepsForAudience, FIRST_LOGIN_TOUR } from "../tourCatalog";

describe("onboarding storage", () => {
  afterEach(() => {
    localStorage.clear();
  });

  it("auto-starts only after a fresh registration offer", () => {
    expect(shouldAutoStartOnboarding()).toBe(false);
    markOnboardingOffer();
    expect(hasOnboardingOffer()).toBe(true);
    expect(shouldAutoStartOnboarding()).toBe(true);
    completeOnboarding();
    expect(isOnboardingDone()).toBe(true);
    expect(shouldAutoStartOnboarding()).toBe(false);
  });
});

describe("tour catalog", () => {
  it("keeps the first-login path for every audience", () => {
    expect(stepsForAudience(false, false).map((s) => s.id)).toEqual(
      FIRST_LOGIN_TOUR.map((s) => s.id),
    );
  });
});
