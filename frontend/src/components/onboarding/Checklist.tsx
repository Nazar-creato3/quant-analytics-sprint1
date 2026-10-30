"use client";

import { FIRST_LOGIN_TOUR } from "@/lib/onboarding/tourCatalog";

/** Optional map of the tour — not a required task list. */
export function OnboardingOutline({ currentId }: { currentId?: string }) {
  return (
    <ol className="space-y-1 text-[11px] text-qa-muted">
      {FIRST_LOGIN_TOUR.map((step, i) => (
        <li
          key={step.id}
          className={step.id === currentId ? "text-qa-text" : undefined}
        >
          {i + 1}. {step.title}
        </li>
      ))}
    </ol>
  );
}
