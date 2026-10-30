"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import { normalizeActiveTicker } from "@/lib/active-ticker";
import { UniverseSearchField } from "@/components/search/UniverseSearchField";
import { useAuth } from "@/hooks";

export function ActiveTickerJump() {
  const { setActiveTicker } = useActiveTicker();
  const { isStaff } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const applyTicker = useCallback(
    (raw: string) => {
      const next = normalizeActiveTicker(raw);
      setActiveTicker(next);
      setOpen(false);
      if (isStaff && pathname === "/screener") {
        router.push(`/terminal?symbol=${encodeURIComponent(next)}`);
      }
    },
    [isStaff, pathname, router, setActiveTicker],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setOpen(true);
        return;
      }
      if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => inputRef.current?.focus(), 20);
    return () => window.clearTimeout(id);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[80] bg-black/70 flex items-start justify-center p-4 pt-[12vh]"
      role="dialog"
      aria-modal
      aria-label="Jump to ticker"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-lg rounded-lg border border-terminal-border bg-terminal-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-3 space-y-2">
          <p className="text-[10px] uppercase tracking-wide text-terminal-muted">
            Active ticker · Ctrl+K
          </p>
          <UniverseSearchField
            inputRef={inputRef}
            onPick={applyTicker}
            placeholder="Тикер или название — список ниже"
          />
        </div>
      </div>
    </div>
  );
}
