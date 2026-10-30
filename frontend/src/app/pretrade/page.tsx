import { redirect } from "next/navigation";

/** The pre-trade check now lives inside the deal window. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const symbol = typeof sp.symbol === "string" ? `?symbol=${encodeURIComponent(sp.symbol)}` : "";
  redirect(`/direct-deals${symbol}`);
}
