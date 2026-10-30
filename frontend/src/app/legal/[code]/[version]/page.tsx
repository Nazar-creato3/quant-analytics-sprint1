import { LegalMarkdownPage } from "@/components/layout/LegalMarkdownPage";

export default function LegalVersionPage({
  params,
}: {
  params: { code: string; version: string };
}) {
  return <LegalMarkdownPage code={params.code} version={params.version} />;
}
