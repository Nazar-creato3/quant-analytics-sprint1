import { legalSlot } from "@/lib/public-site";

export function LegalSlot({ title }: { title: string }) {
  const lines = legalSlot(title);
  return (
    <main className="mx-auto max-w-3xl bg-white p-4 text-neutral-800">
      <h1 className="text-lg font-medium">{lines[0]}</h1>
      <p className="mt-2 text-sm text-neutral-700">{lines[1]}</p>
      <p className="mt-1 text-sm text-neutral-700">{lines[2]}</p>
    </main>
  );
}
