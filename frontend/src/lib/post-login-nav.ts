/** Safe in-app redirect target after login (blocks open redirects). */
export function safeRedirectPath(from: string | null): string {
  if (!from || !from.startsWith("/") || from.startsWith("//")) return "/";
  return from;
}

const ENROLL_2FA_KEY = "qa_2fa_enroll";

export function markTwoFactorEnrollmentRequired(): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(ENROLL_2FA_KEY, "1");
  } catch {
    /* ignore */
  }
}

/**
 * Full navigation after auth — bypasses stale PWA/HTML cache and ensures middleware sees the cookie.
 * Admins without 2FA are sent to Settings → 2FA.
 */
export function navigateAfterLogin(from: string | null): void {
  if (typeof window === "undefined") return;
  let enroll = false;
  try {
    enroll = sessionStorage.getItem(ENROLL_2FA_KEY) === "1";
    if (enroll) sessionStorage.removeItem(ENROLL_2FA_KEY);
  } catch {
    /* ignore */
  }
  const target = enroll ? "/settings#two-factor" : safeRedirectPath(from);
  window.location.replace(target);
}
