"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useMemo, useState } from "react";
import { toast } from "react-hot-toast";
import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { AdmissionsTable } from "@/components/operator/AdmissionsTable";
import {
  AdmissionActionButtons,
  BUCKET_LABELS,
  type AdmissionActionRow,
} from "@/components/operator/AdmissionActionButtons";
import { admissionsApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { AdmissionsSubnav } from "@/components/operator/AdmissionsSubnav";

const BUCKET_ORDER = ["paying", "full", "trial", "blocked"] as const;

export default function AdmissionsPage() {
  const qc = useQueryClient();
  const [viewMode, setViewMode] = useState<"kanban" | "table">("table");
  const [tableStatusFilter, setTableStatusFilter] = useState("");
  const [tableSort, setTableSort] = useState("created_at_desc");
  const [tablePage, setTablePage] = useState(1);
  const tablePageSize = 15;

  const { data, isLoading } = useQuery({
    queryKey: ["admissions-board"],
    queryFn: () => admissionsApi.list(),
    refetchInterval: 30_000,
    enabled: viewMode === "kanban",
  });

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [capital, setCapital] = useState("");
  const [source, setSource] = useState("manual");

  const createMut = useMutation({
    mutationFn: () =>
      admissionsApi.create({
        contact_email: email,
        contact_name: name || null,
        capital_range: capital || null,
        source,
      }),
    onSuccess: () => {
      toast.success("Лид создан");
      setEmail("");
      setName("");
      qc.invalidateQueries({ queryKey: ["admissions-board"] });
      qc.invalidateQueries({ queryKey: ["admissions-list"] });
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось создать")),
  });

  const buckets = useMemo(
    () => (data as { buckets?: Record<string, AdmissionActionRow[]> } | undefined)?.buckets ?? {},
    [data],
  );

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admissions-board"] });
    qc.invalidateQueries({ queryKey: ["admissions-list"] });
  };

  const runAction = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      invalidate();
    } catch (e) {
      toast.error(extractErrorMessage(e, "Не удалось"));
    }
  };

  return (
    <OperatorDetailShell
      title="Допуски"
      description="Доступ клиентов: полный доступ, права админа, ограничение."
      fillViewport
    >
      <div className="flex flex-col flex-1 min-h-0 gap-4 overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <AdmissionsSubnav />
          <div className="inline-flex rounded border border-cockpit-border overflow-hidden">
            <button
              type="button"
              className={clsx(
                "text-xs px-3 py-1.5",
                viewMode === "table"
                  ? "bg-[var(--qa-active)] text-terminal-accent"
                  : "text-qa-muted hover:bg-cockpit-panel-raised/40",
              )}
              onClick={() => setViewMode("table")}
            >
              Таблица
            </button>
            <button
              type="button"
              className={clsx(
                "text-xs px-3 py-1.5 border-l border-cockpit-border",
                viewMode === "kanban"
                  ? "bg-[var(--qa-active)] text-terminal-accent"
                  : "text-qa-muted hover:bg-cockpit-panel-raised/40",
              )}
              onClick={() => setViewMode("kanban")}
            >
              Kanban
            </button>
          </div>
        </div>

        {viewMode === "table" ? (
          <AdmissionsTable
            statusFilter={tableStatusFilter}
            sort={tableSort}
            page={tablePage}
            pageSize={tablePageSize}
            onStatusFilterChange={setTableStatusFilter}
            onSortChange={setTableSort}
            onPageChange={setTablePage}
          />
        ) : (
          <>
            <div className="cockpit-panel p-4 grid grid-cols-1 md:grid-cols-5 gap-2 items-end shrink-0">
              <label className="text-xs space-y-1">
                <span className="text-qa-muted">Email</span>
                <input
                  className="input w-full text-xs"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="lead@email.com"
                />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-qa-muted">Имя</span>
                <input
                  className="input w-full text-xs"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-qa-muted">Капитал</span>
                <input
                  className="input w-full text-xs"
                  value={capital}
                  onChange={(e) => setCapital(e.target.value)}
                  placeholder="50-100k"
                />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-qa-muted">Source</span>
                <input
                  className="input w-full text-xs"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                />
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-primary text-xs"
                  disabled={!email || createMut.isPending}
                  onClick={() => createMut.mutate()}
                >
                  Create lead
                </button>
              </div>
            </div>

            {isLoading ? (
              <div className="skeleton h-40 rounded-lg shrink-0" />
            ) : (
              <div className="flex-1 flex gap-3 overflow-x-auto overflow-y-hidden min-h-0 pb-2">
                {BUCKET_ORDER.map((bucket) => (
                  <div
                    key={bucket}
                    className="min-w-[220px] flex-1 flex flex-col min-h-0 cockpit-panel p-2"
                  >
                    <div className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold px-1 py-2 flex justify-between shrink-0">
                      <span>{BUCKET_LABELS[bucket]}</span>
                      <span>{(buckets[bucket] ?? []).length}</span>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto space-y-2">
                      {(buckets[bucket] ?? []).map((c) => (
                        <div
                          key={c.id}
                          className="rounded-md border border-cockpit-border bg-black/20 p-2 text-[11px] space-y-2"
                        >
                          <div className="font-semibold text-white truncate">
                            {c.contact_name || c.contact_email}
                          </div>
                          <div className="text-qa-muted truncate">{c.contact_email}</div>
                          {c.capital_range ? (
                            <div className="text-terminal-accent/90">{c.capital_range}</div>
                          ) : null}
                          <AdmissionActionButtons
                            row={c}
                            onFullAccess={() =>
                              runAction(() => admissionsApi.approve(c.id), "Полный доступ выдан")
                            }
                            onAdmin={() =>
                              runAction(() => admissionsApi.grantAdmin(c.id), "Права админа выданы")
                            }
                            onRevokeAdmin={() =>
                              runAction(
                                () => admissionsApi.revokeAdmin(c.id),
                                "Права админа отозваны",
                              )
                            }
                            onSuspend={() =>
                              runAction(
                                () => admissionsApi.suspend(c.id),
                                "Полный доступ ограничен",
                              )
                            }
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </OperatorDetailShell>
  );
}
