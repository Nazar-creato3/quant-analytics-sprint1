/** Display-safe truncation — no mid-word cuts or dangling «MACD:» / «Новостно». */

const INCOMPLETE_LABEL_TAIL =
  /\s+(?:MACD|RSI|Объём|R:R|Режим|Новостной фон)\s*:\s*$/i;

function stripIncompleteTail(text: string): string {
  let cleaned = text.trim();
  if (!cleaned) return "";

  let prev = "";
  while (prev !== cleaned) {
    prev = cleaned;
    cleaned = cleaned.replace(INCOMPLETE_LABEL_TAIL, "").replace(/[.,;:]+$/, "").trim();
  }
  return cleaned;
}

export function trimDisplayText(text: string | null | undefined, maxLen: number): string {
  const cleaned = (text ?? "").trim();
  if (!cleaned) return "";
  if (cleaned.length <= maxLen) return stripIncompleteTail(cleaned);

  let chunk = cleaned.slice(0, maxLen);
  let splitAtSep = false;
  for (const sep of [". ", "; ", ", ", " "]) {
    const idx = chunk.lastIndexOf(sep);
    if (idx > maxLen * 0.45) {
      chunk = chunk.slice(0, idx + (sep.trim() === "." ? 1 : 0));
      splitAtSep = true;
      break;
    }
  }
  if (!splitAtSep) {
    chunk = chunk.trimEnd();
  }

  if (chunk && /[A-Za-zА-Яа-я0-9]$/.test(chunk) && cleaned.length > chunk.length) {
    const spaceIdx = chunk.lastIndexOf(" ");
    if (spaceIdx > 0) chunk = chunk.slice(0, spaceIdx);
  }

  const result = stripIncompleteTail(chunk.replace(/[.,;:]+$/, "").trim());
  return result ? `${result}…` : "…";
}
