import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

import { SubjectRightsCard } from "@/components/account/SubjectRightsCard";

describe("subject rights card", () => {
  it("offers export and delete for the session user, no advice or contact data", () => {
    const html = renderToStaticMarkup(<SubjectRightsCard />);
    expect(html).toContain("Скачать мои данные");
    expect(html).toContain("Удалить аккаунт");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("рекомендуем");
    expect(html).not.toContain("@");
  });

  it("does not ask the user to type an identifier and matches the dark theme", () => {
    const html = renderToStaticMarkup(<SubjectRightsCard />);
    expect(html).not.toContain('name="user_id"');
    expect(html).not.toContain("bg-white");
    expect(html).toContain("bg-cockpit-surface");
  });
});
