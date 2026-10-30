import { partnerLines } from "@/lib/partners";

export function PartnerBlock({ disclosure }: { disclosure?: string }) {
  const lines = partnerLines(disclosure);
  return (
    <section aria-labelledby="partner-offer-title" className="rounded-xl border border-qa-border p-3 text-sm">
      <h2 id="partner-offer-title" className="font-medium">
        {lines[0]}
      </h2>
      <p className="mt-1 text-xs text-qa-muted">{lines[1]}</p>
      <p className="mt-1 text-xs text-qa-muted">{lines[2]}</p>
    </section>
  );
}
