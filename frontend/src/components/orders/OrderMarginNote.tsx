import { marginLines } from "@/lib/order-machine";

/** Margin facts the broker has not given us yet — folded so they do not crowd the ticket. */
export function OrderMarginNote() {
  const lines = marginLines();
  return (
    <details className="mb-3 text-xs text-qa-muted">
      <summary id="order-margin-title" className="cursor-pointer select-none text-qa-muted hover:text-qa-text">
        Обеспечение и плечо
      </summary>
      <ul className="mt-1 pl-3">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </details>
  );
}
