export async function lane2Get(path: string): Promise<Record<string, unknown>> {
  try {
    const res = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
    if (!res.ok) return { status: "нет данных" };
    const row = await res.json();
    return row && typeof row === "object" ? (row as Record<string, unknown>) : { status: "нет данных" };
  } catch {
    return { status: "нет данных" };
  }
}

export async function lane2Post(path: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  try {
    const res = await fetch(`/api/v1${path}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return { status: "нет данных" };
    const row = await res.json();
    return row && typeof row === "object" ? (row as Record<string, unknown>) : { status: "нет данных" };
  } catch {
    return { status: "нет данных" };
  }
}
