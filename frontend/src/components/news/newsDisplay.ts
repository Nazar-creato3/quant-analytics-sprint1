import type { NewsArticle } from "@/types";

export function displayNewsTitle(article: NewsArticle): string {
  return article.title_ru?.trim() || article.title;
}

export function displayNewsSummary(article: NewsArticle): string | null {
  const summary =
    article.summary_ru?.trim() ||
    article.description?.trim() ||
    null;
  return summary || null;
}

/** Machine translation stays on titles/summaries; badge UI intentionally hidden. */
export function showMachineTranslationBadge(_article: NewsArticle): boolean {
  return false;
}
