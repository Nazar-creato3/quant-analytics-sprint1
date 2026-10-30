/** Lightweight stable browser fingerprint (Prompt 58) — no FingerprintJS dependency. */
export async function getBrowserFingerprint(): Promise<string> {
  if (typeof window === "undefined") return "server";
  const parts = [
    navigator.userAgent,
    navigator.language,
    String(screen.width),
    String(screen.height),
    String(screen.colorDepth),
    Intl.DateTimeFormat().resolvedOptions().timeZone || "",
    String(new Date().getTimezoneOffset()),
  ];
  try {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.textBaseline = "top";
      ctx.font = "14px Arial";
      ctx.fillText("apex-fp", 2, 2);
      parts.push(canvas.toDataURL().slice(0, 64));
    }
  } catch {
    /* ignore */
  }
  const raw = parts.join("|");
  const data = new TextEncoder().encode(raw);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
