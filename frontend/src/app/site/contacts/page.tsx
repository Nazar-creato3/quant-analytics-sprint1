import { contactLines } from "@/lib/public-site";

export default function ContactsSlotPage() {
  const lines = contactLines();
  return (
    <main className="mx-auto max-w-3xl bg-white p-4 text-neutral-800">
      <h1 className="text-lg font-medium">{lines[0]}</h1>
      <p className="mt-2 text-sm text-neutral-700">{lines[1]}</p>
    </main>
  );
}
