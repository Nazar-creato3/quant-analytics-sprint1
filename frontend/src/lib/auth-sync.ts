/** Restore API auth from middleware cookie when localStorage was cleared (hard refresh). */

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function syncAuthFromCookie(): void {
  if (typeof window === "undefined") return;
  const cookieToken = readCookie("access_token");
  if (!cookieToken) return;
  if (!localStorage.getItem("access_token")) {
    localStorage.setItem("access_token", cookieToken);
  }
}
