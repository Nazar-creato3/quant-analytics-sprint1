import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveOrderCancelled, confirmLiveOrNot, currentBookMode } from "../api";

describe("currentBookMode", () => {
  afterEach(() => window.localStorage.clear());

  it("defaults to paper", () => {
    expect(currentBookMode()).toBe("paper");
  });

  it("reads the header choice", () => {
    window.localStorage.setItem("qa.bookMode", "live");
    expect(currentBookMode()).toBe("live");
  });
});

describe("confirmLiveOrNot", () => {
  afterEach(() => vi.restoreAllMocks());

  it("never asks on paper", () => {
    const spy = vi.spyOn(window, "confirm");
    confirmLiveOrNot("paper");
    expect(spy).not.toHaveBeenCalled();
  });

  it("stops a live order the user did not confirm", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    expect(() => confirmLiveOrNot("live")).toThrow(LiveOrderCancelled);
  });

  it("lets a confirmed live order through", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    expect(() => confirmLiveOrNot("live")).not.toThrow();
  });
});
