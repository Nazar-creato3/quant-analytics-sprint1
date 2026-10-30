/** React Query keys scoped to the authenticated user — prevents cross-tab cache bleed. */

export function userQueryKey(
  userKey: string | undefined,
  ...parts: readonly unknown[]
): readonly unknown[] {
  return ["user", userKey ?? "anonymous", ...parts] as const;
}

export const AUTH_SESSION_CHANGED_EVENT = "apex-auth-session-changed";

export function notifyAuthSessionChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT));
}
