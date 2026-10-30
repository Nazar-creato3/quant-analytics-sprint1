export type LegalDocument = {
  code: string;
  version: string;
  effective_date: string | null;
  status: "draft" | "approved";
  approved_by: string | null;
  sha256: string;
  body: string;
  path: string;
  draft_badge: boolean;
};

function apiBase(): string {
  if (typeof window !== "undefined") {
    const port = window.location.port;
    if (port === "3120" || port === "3150" || port === "3000" || port === "3100" || window.location.hostname === "frontend") {
      return "";
    }
  }
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  return "";
}

export async function fetchLegalDocument(
  code: string,
  version?: string,
): Promise<LegalDocument> {
  const suffix = version ? `/${encodeURIComponent(version)}` : "";
  const response = await fetch(`${apiBase()}/api/v1/legal/${encodeURIComponent(code)}${suffix}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`legal ${code} ${response.status}`);
  }
  return (await response.json()) as LegalDocument;
}

export async function fetchUiTexts(): Promise<Record<string, unknown>> {
  const response = await fetch(`${apiBase()}/api/v1/legal/ui-texts`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`ui-texts ${response.status}`);
  }
  return (await response.json()) as Record<string, unknown>;
}
