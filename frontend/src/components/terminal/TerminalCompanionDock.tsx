"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Play, RefreshCw, Upload, X } from "lucide-react";
import Link from "next/link";
import {
  companionLaunch,
  companionPushWatchlist,
  companionSnapshot,
  probeFinceptCompanion,
} from "@/lib/fincept-companion";
import { watchlistApi } from "@/lib/api";
import { useAuth } from "@/hooks";
export function TerminalCompanionDock({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { isAdmin } = useAuth();

  const companionQ = useQuery({
    queryKey: ["fincept-companion-status"],
    queryFn: probeFinceptCompanion,
    refetchInterval: open ? 8_000 : false,
    retry: false,
    enabled: open,
  });

  const watchQ = useQuery({
    queryKey: ["watchlists-effective"],
    queryFn: () => watchlistApi.effective(),
    staleTime: 60_000,
    enabled: open,
  });

  const companionOnline = Boolean(companionQ.data);
  const canLaunch = companionOnline && Boolean(companionQ.data?.runnable);
  const qaSymbols: string[] = watchQ.data?.tickers ?? [];

  const launchMut = useMutation({
    mutationFn: async () => {
      if (!companionQ.data) {
        throw new Error("Настольный терминал недоступен");
      }
      return companionLaunch();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["fincept-companion-status"] });
    },
  });

  const snapMut = useMutation({
    mutationFn: async () => {
      if (!companionQ.data) {
        throw new Error("Настольный терминал недоступен");
      }
      return companionSnapshot();
    },
  });

  const pushMut = useMutation({
    mutationFn: async (symbols: string[]) => {
      if (!companionQ.data) {
        throw new Error("Настольный терминал недоступен");
      }
      return companionPushWatchlist(symbols);
    },
    onSuccess: () => snapMut.mutate(),
  });

  if (!open) return null;

  return (
    <div className="border-t border-terminal-border bg-terminal-panel shrink-0">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-terminal-border">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wider text-terminal-accent">
            Настольный терминал
          </p>
          <p className="text-[9px] text-terminal-muted">
            Дополнительное окно на этом компьютере
          </p>
        </div>
        <button type="button" className="term-btn" onClick={onClose} aria-label="Закрыть">
          <X size={12} />
        </button>
      </div>
      <div className="px-3 py-2 flex flex-wrap items-center gap-2 text-[10px]">
        <span className={clsx("term-pill", companionOnline && "on")}>
          {companionOnline ? "подключён" : "не подключён"}
        </span>
        <button
          type="button"
          className="term-btn term-btn-primary"
          disabled={launchMut.isPending || !canLaunch}
          onClick={() => launchMut.mutate()}
        >
          <Play size={11} aria-hidden />
          {launchMut.isPending ? "Открытие…" : "Открыть"}
        </button>
        <button
          type="button"
          className="term-btn"
          disabled={snapMut.isPending || !companionOnline}
          onClick={() => snapMut.mutate()}
        >
          <RefreshCw size={11} aria-hidden />
          Обновить список
        </button>
        <button
          type="button"
          className="term-btn"
          disabled={pushMut.isPending || qaSymbols.length === 0 || !companionOnline}
          onClick={() => pushMut.mutate(qaSymbols)}
        >
          <Upload size={11} aria-hidden />
          Отправить список
        </button>
        {isAdmin && (
          <Link href="/ops/crypto-integrations" className="term-btn">
            Подключения
          </Link>
        )}
        {(launchMut.error || pushMut.error) && (
          <span className="term-down text-[9px]">
            Не удалось выполнить действие
          </span>
        )}
      </div>
    </div>
  );
}
