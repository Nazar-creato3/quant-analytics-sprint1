import { LegalPageShell } from "@/components/layout/LegalPageShell";
import { ENTITY_SECTIONS } from "@/content/legal/entity";

export default function LegalEntityPage() {
  return (
    <LegalPageShell
      title="Юридическое лицо"
      subtitle="Оператор платформы, реквизиты и контакты."
      sections={ENTITY_SECTIONS}
    />
  );
}
