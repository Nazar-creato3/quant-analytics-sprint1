import Link from "next/link";

export function SupportLink() {
  return (
    <p className="px-4 py-2 text-xs text-qa-muted">
      <Link href="/support">Сообщить о проблеме</Link>
    </p>
  );
}
