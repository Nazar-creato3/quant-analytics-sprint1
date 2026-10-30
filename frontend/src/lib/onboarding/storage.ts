export const ONBOARDING_OFFER_KEY = "qa.onboarding.v1.offer";
export const ONBOARDING_DONE_KEY = "qa.onboarding.v1.done";

export function markOnboardingOffer(): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ONBOARDING_OFFER_KEY, "1");
}

export function hasOnboardingOffer(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(ONBOARDING_OFFER_KEY) === "1";
}

export function isOnboardingDone(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(ONBOARDING_DONE_KEY) === "1";
}

export function completeOnboarding(): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ONBOARDING_DONE_KEY, "1");
  window.localStorage.removeItem(ONBOARDING_OFFER_KEY);
}

export function shouldAutoStartOnboarding(): boolean {
  return hasOnboardingOffer() && !isOnboardingDone();
}
