import { BackButton } from "@/components/layout/BackButton";
import { methodologyLines } from "@/lib/public-methodology";

export function MethodologyBody() {
  const lines = methodologyLines();
  return (
    <main className="mx-auto max-w-3xl p-4">
      <BackButton className="mb-3" />
      <h1 className="text-lg font-medium">Методика</h1>
      {lines.map((line) => (
        <section key={line.title} className="mt-3">
          <h2 className="text-sm font-medium">{line.title}</h2>
          <p className="mt-1 text-sm text-qa-muted">{line.body}</p>
        </section>
      ))}
    </main>
  );
}
