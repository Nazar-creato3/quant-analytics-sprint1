"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { tradingAccountsApi, type BrokerVenue } from "@/lib/api";
import type { BookMode } from "@/contexts/ProductContext";

type AccountsOverview = Awaited<ReturnType<typeof tradingAccountsApi.list>>;

/** Re-load the broker account when it is older than this. */
export const BROKER_SYNC_STALE_MS = 15 * 60 * 1000;

export function hasBrokerKey(overview: AccountsOverview | undefined, mode: BookMode, venue: BrokerVenue): boolean {
  const names = venue === "tinkoff" ? ["tinkoff", "tbank"] : [venue];
  return (overview?.venues || []).some(
    (v) => names.includes(v.venue) && v.connected_accounts.some((a) => a.connected && a.account_mode === mode),
  );
}

/** Kept for callers that only care about T-Bank. */
export function hasTinkoffKey(overview: AccountsOverview | undefined, mode: BookMode): boolean {
  return hasBrokerKey(overview, mode, "tinkoff");
}

export function syncIsStale(lastSyncs: (string | null)[], now: number = Date.now()): boolean {
  if (!lastSyncs.length) return true;
  const times = lastSyncs.map((t) => (t ? Date.parse(t) : NaN));
  if (times.some((t) => Number.isNaN(t))) return true;
  return now - Math.min(...times) > BROKER_SYNC_STALE_MS;
}

/**
 * When the user works in a mode that has a connected broker key, keep the
 * book fresh: one background sync per broker and page load once stale.
 */
function useOneBrokerAutoSync(mode: BookMode, venue: BrokerVenue, overview: AccountsOverview | undefined) {
  const qc = useQueryClient();
  const tried = useRef<Set<string>>(new Set());
  const keyOn = hasBrokerKey(overview, mode, venue);
  const { data: synced } = useQuery({
    queryKey: ["broker-accounts", venue, mode],
    queryFn: () => tradingAccountsApi.brokerAccounts(venue, mode),
    enabled: keyOn,
    staleTime: 60_000,
  });
  const sync = useMutation({
    mutationFn: () => tradingAccountsApi.syncBroker(venue, mode),
    onSettled: () => void qc.invalidateQueries(),
  });
  useEffect(() => {
    const tag = `${venue}:${mode}`;
    if (!keyOn || !synced || tried.current.has(tag) || sync.isPending) return;
    if (!syncIsStale(synced.accounts.map((a) => a.last_sync))) return;
    tried.current.add(tag);
    sync.mutate();
  }, [keyOn, synced, mode, venue, sync]);
  return { syncing: sync.isPending, keyOn, lastSync: synced?.accounts[0]?.last_sync ?? null };
}

export function useBrokerAutoSync(mode: BookMode) {
  const { data: overview } = useQuery({
    queryKey: ["trading-accounts"],
    queryFn: tradingAccountsApi.list,
    staleTime: 60_000,
  });
  const tbank = useOneBrokerAutoSync(mode, "tinkoff", overview);
  const finam = useOneBrokerAutoSync(mode, "finam", overview);
  return {
    syncing: tbank.syncing || finam.syncing,
    keyOn: tbank.keyOn || finam.keyOn,
    lastSync: tbank.lastSync ?? finam.lastSync,
  };
}
