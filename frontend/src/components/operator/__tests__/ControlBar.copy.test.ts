import { describe, expect, it } from "vitest";
import { CONTROL_BAR_COPY } from "@/components/operator/ControlBar";

describe("ControlBar user copy", () => {
  it("keeps mode and broker labels in Russian without ops jargon", () => {
    expect(CONTROL_BAR_COPY.paper).toBe("Учебный");
    expect(CONTROL_BAR_COPY.live).toBe("Боевой");
    expect(CONTROL_BAR_COPY.db).toBe("База");
    expect(CONTROL_BAR_COPY.cache).toBe("Кэш");
    expect(CONTROL_BAR_COPY.venue).toBe("Площадка");
    expect(Object.values(CONTROL_BAR_COPY).join(" ")).not.toMatch(
      /\b(Paper|Live|DB|Cache|Venue)\b/,
    );
  });
});
