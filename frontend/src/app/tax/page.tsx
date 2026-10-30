import { redirect } from "next/navigation";

/** Merged into the single «Портфель» page. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const symbol = typeof sp.symbol === "string" ? `&add=${encodeURIComponent(sp.symbol)}` : "";
  redirect(`/portfolio?tab=costs${symbol}`);
}
