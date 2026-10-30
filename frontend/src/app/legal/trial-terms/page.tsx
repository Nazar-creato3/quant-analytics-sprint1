import { LegalPageShell } from "@/components/layout/LegalPageShell";
import { TRIAL_TERMS_SECTIONS } from "@/content/legal/trial-terms";

export default function TrialTermsPage() {
  return (
    <LegalPageShell
      title="Условия пробного доступа (trial)"
      subtitle="2 календарных дня: дашборд, графики и paper/demo без live-торговли."
      sections={TRIAL_TERMS_SECTIONS}
    />
  );
}
