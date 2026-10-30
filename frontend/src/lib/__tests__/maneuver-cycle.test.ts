import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ManeuverCycleCard } from "@/components/act/ManeuverCycleCard";
import { ManeuverHistory } from "@/components/act/ManeuverHistory";
import { filterByStatus, statusLabel } from "@/lib/maneuver-cycle";

const noop = () => undefined;

describe("maneuver cycle labels", () => {
  it("uses a Russian status and keeps a missing status as нет данных", () => {
    expect(statusLabel("sent")).toBe("отправлен");
    expect(statusLabel("unknown")).toBe("нет данных");
    expect(filterByStatus([{ status: "closed" }, { status: "rejected" }], "closed")).toHaveLength(1);
  });

  it("renders named controls for the viewed card", () => {
    const html = renderToStaticMarkup(
      createElement(ManeuverCycleCard, {
        item: {
          id: "m-1",
          status: "viewed",
          rationale: "доля выше правила",
          qty: "1",
          expires_at: "2026-10-08T00:00:00+00:00",
          impact: { delta: { var_95: { before: "0.1", after: "0.08" } }, costs: { total: null } },
        },
        onView: noop,
        onEdit: noop,
        onApprove: noop,
        onReject: noop,
        onSend: noop,
        onExecute: noop,
        onClose: noop,
      }),
    );
    expect(html).toContain("просмотрен");
    expect(html).not.toContain(">viewed<");
    expect(html).toContain("Количество");
    expect(html).toContain("Подтверждаю одобрение");
    expect(html).toContain("Одобрить");
    expect(html).toContain("disabled");
    expect(html).toContain("Причина отклонения");
    expect(html).toContain("Издержки: нет данных");
    expect(html).toContain('aria-labelledby="maneuver-m-1"');
  });

  it("renders a labelled history filter", () => {
    const html = renderToStaticMarkup(
      createElement(ManeuverHistory, {
        items: [
          { id: "a", status: "rejected", rationale: "первая" },
          { id: "b", status: "closed", rationale: "вторая" },
        ],
      }),
    );
    expect(html).toContain('for="maneuver-status-filter"');
    expect(html).toContain("Состояние");
    expect(html).toContain("первая");
    expect(html).toContain("вторая");
    expect(html).toContain("отклонён");
  });
});