import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Debug/health: verify Supabase env + optional crypto_data read.
 * Does not expose service_role or other secrets.
 */
export async function GET(_request: NextRequest) {
  const urlConfigured = Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL);
  const keyConfigured = Boolean(process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY);

  if (!urlConfigured || !keyConfigured) {
    return NextResponse.json(
      {
        ok: false,
        supabase: { urlConfigured, keyConfigured },
        error: "env_missing",
      },
      { status: 503 },
    );
  }

  try {
    const supabase = await createClient();
    const { data, error, count } = await supabase
      .from("crypto_data")
      .select("id,symbol,price,timestamp", { count: "exact" })
      .order("timestamp", { ascending: false })
      .limit(5);

    return NextResponse.json({
      ok: !error,
      supabase: {
        urlConfigured,
        keyConfigured,
        projectHost: process.env.NEXT_PUBLIC_SUPABASE_URL?.replace(/^https?:\/\//, ""),
      },
      crypto_data: {
        sample: data ?? [],
        count: count ?? null,
        error: error?.message ?? null,
      },
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        supabase: { urlConfigured, keyConfigured },
        error: err instanceof Error ? err.message : "unknown",
      },
      { status: 500 },
    );
  }
}
