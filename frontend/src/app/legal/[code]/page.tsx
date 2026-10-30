import { LegalMarkdownPage } from "@/components/layout/LegalMarkdownPage";

export default function LegalCodePage({ params }: { params: { code: string } }) {
  return <LegalMarkdownPage code={params.code} />;
}
