"use client";

import { useEffect } from "react";
import type { TerminalDensity } from "@/types/terminal";

export type TerminalShortcutHandlers = {
  toggleDensity: () => void;
  refresh: () => void;
  focusWatch: () => void;
  focusChat: () => void;
  toggleHelp: () => void;
  closeOverlays: () => void;
  toggleCompanion: () => void;
  setDensity: (d: TerminalDensity) => void;
};

export function useTerminalShortcuts(handlers: TerminalShortcutHandlers, enabled = true) {
  useEffect(() => {
    if (!enabled) return;

    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      const typing =
        tag === "input" ||
        tag === "textarea" ||
        tag === "select" ||
        target?.isContentEditable;

      if (e.key === "?" && !typing) {
        e.preventDefault();
        handlers.toggleHelp();
        return;
      }
      if (e.key === "Escape") {
        handlers.closeOverlays();
        return;
      }
      if (typing) return;

      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        return;
      }
      if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        handlers.refresh();
        return;
      }
      if (e.key === "d" || e.key === "D") {
        e.preventDefault();
        handlers.toggleDensity();
        return;
      }
      if (e.key === "w" || e.key === "W") {
        e.preventDefault();
        handlers.focusWatch();
        return;
      }
      if (e.key === "/" || e.key === "c" || e.key === "C") {
        if (e.key === "/") {
          e.preventDefault();
          handlers.focusChat();
          return;
        }
        if (!e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          handlers.toggleCompanion();
        }
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handlers, enabled]);
}

export const TERMINAL_SHORTCUT_HELP: Array<{ keys: string; action: string }> = [
  { keys: "Ctrl+K", action: "Jump to ticker (activeTicker)" },
  { keys: "R", action: "Refresh snapshot" },
  { keys: "D", action: "Toggle density" },
  { keys: "W", action: "Focus watchlist" },
  { keys: "/", action: "Focus AI chat" },
  { keys: "C", action: "Companion dock" },
  { keys: "?", action: "Shortcuts help" },
  { keys: "Esc", action: "Close overlays" },
];
