import { subscriptionLines } from "@/lib/subscription-billing";

export function SubscriptionCard() {
  const lines = subscriptionLines();
  return (
    <section aria-labelledby="subscription-title" className="rounded-xl border border-qa-border p-3 text-sm">
      <h2 id="subscription-title" className="font-medium">
        {lines[0]}
      </h2>
      <p className="mt-1 text-xs text-qa-muted">{lines[1]}</p>
      <p className="mt-1 text-xs text-qa-muted">{lines[2]}</p>
    </section>
  );
}
