/** Query params that must never carry credentials (security). */
export const SENSITIVE_LOGIN_QUERY_PARAMS = [
  "email",
  "password",
  "pass",
  "pwd",
  "username",
  "user",
] as const;

/** Legacy keys that must never persist passwords client-side. */
export const LEGACY_CREDENTIAL_STORAGE_KEYS = [
  "email",
  "password",
  "login_email",
  "login_password",
  "auth_email",
  "auth_password",
] as const;

export function stripSensitiveLoginQueryParams(url: URL): URL {
  const cleaned = new URL(url.toString());
  let changed = false;
  for (const key of SENSITIVE_LOGIN_QUERY_PARAMS) {
    if (cleaned.searchParams.has(key)) {
      cleaned.searchParams.delete(key);
      changed = true;
    }
  }
  return changed ? cleaned : url;
}

export function urlHasSensitiveLoginQueryParams(url: URL | string): boolean {
  const parsed = typeof url === "string" ? new URL(url) : url;
  return SENSITIVE_LOGIN_QUERY_PARAMS.some((key) => parsed.searchParams.has(key));
}

/** Remove any client-side credential storage (passwords must never be stored). */
export function clearLegacyCredentialStorage(): void {
  if (typeof window === "undefined") return;
  for (const key of LEGACY_CREDENTIAL_STORAGE_KEYS) {
    try {
      localStorage.removeItem(key);
      sessionStorage.removeItem(key);
    } catch {
      /* private mode / quota */
    }
  }
}
