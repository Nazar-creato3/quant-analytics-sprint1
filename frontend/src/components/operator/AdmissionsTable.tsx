"use client";

import { clsx } from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { toast } from "react-hot-toast";
import { admissionsApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import type { PaginatedResponse } from "@/types";
import { Spinner } from "@/components/ui";
import { AdmissionActionButtons, BUCKET_LABELS, type AdmissionActionRow } from "./AdmissionActionButtons";

const FILTER_BUCKETS = [
  { value: "", label: "Все категории" },
  { value: "paying", label: BUCKET_LABELS.paying },
  { value: "full", label: BUCKET_LABELS.full },
  { value: "trial", label: BUCKET_LABELS.trial },
  { value: "blocked", label: BUCKET_LABELS.blocked },
] as const;

const SORT_OPTIONS = [
  { value: "created_at_desc", label: "Создан ↓" },
  { value: "created_at_asc", label: "Создан ↑" },
  { value: "updated_at_desc", label: "Обновлён ↓" },
  { value: "email_asc", label: "Email A→Z" },
  { value: "email_desc", label: "Email Z→A" },
  { value: "status_asc", label: "Статус A→Z" },
] as const;

interface AdmissionsTableProps {
  statusFilter: string;
  sort: string;
  page: number;
  pageSize: number;
  onStatusFilterChange: (value: string) => void;
  onSortChange: (value: string) => void;
  onPageChange: (page: number) => void;
}

export function AdmissionsTable({
  statusFilter,
  sort,
  page,
  pageSize,
  onStatusFilterChange,
  onSortChange,
  onPageChange,
}: AdmissionsTableProps) {
  const qc = useQueryClient();
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["admissions-list", statusFilter, sort, page, pageSize],
    queryFn: () =>
      admissionsApi.listPaginated({
        bucket: statusFilter || undefined,
        sort,
        page,
        page_size: pageSize,
      }),
    refetchInterval: 30_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admissions-list"] });
    qc.invalidateQueries({ queryKey: ["admissions-board"] });
  };

  const approveMut = useMutation({
    mutationFn: (id: string) => admissionsApi.approve(id),
    onSuccess: () => {
      toast.success("Полный доступ выдан");
      invalidate();
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось выдать доступ")),
  });
  const adminMut = useMutation({
    mutationFn: (id: string) => admissionsApi.grantAdmin(id),
    onSuccess: () => {
      toast.success("Права админа выданы");
      invalidate();
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось выдать админа")),
  });
  const revokeAdminMut = useMutation({
    mutationFn: (id: string) => admissionsApi.revokeAdmin(id),
    onSuccess: () => {
      toast.success("Права админа отозваны");
      invalidate();
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось отозвать админа")),
  });
  const suspendMut = useMutation({
    mutationFn: (id: string) => admissionsApi.suspend(id),
    onSuccess: () => {
      toast.success("Полный доступ ограничен");
      invalidate();
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось ограничить доступ")),
  });

  const paginated = data as PaginatedResponse<AdmissionActionRow> | undefined;
  const rows = paginated?.items ?? [];
  const total = paginated?.total ?? 0;
  const pages = paginated?.pages ?? 1;
  const pending =
    approveMut.isPending || adminMut.isPending || revokeAdminMut.isPending || suspendMut.isPending;

  return (
    <div className="cockpit-panel flex flex-col flex-1 min-h-0 overflow-hidden">
      <div className="p-3 border-b border-cockpit-border flex flex-wrap gap-2 items-center shrink-0">
        <label className="text-xs flex items-center gap-2">
          <span className="text-qa-muted">Категория</span>
          <select
            className="input text-xs py-1"
            value={statusFilter}
            onChange={(e) => {
              onStatusFilterChange(e.target.value);
              onPageChange(1);
            }}
          >
            {FILTER_BUCKETS.map((opt) => (
              <option key={opt.value || "all"} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs flex items-center gap-2">
          <span className="text-qa-muted">Сортировка</span>
          <select
            className="input text-xs py-1"
            value={sort}
            onChange={(e) => {
              onSortChange(e.target.value);
              onPageChange(1);
            }}
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <span className="text-xs text-qa-muted ml-auto tabular-nums">
          {total} записей · стр. {page} / {pages}
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-cockpit-panel z-10">
            <tr className="text-left text-qa-muted border-b border-cockpit-border">
              <th className="px-3 py-2 font-semibold">Имя / Email</th>
              <th className="px-3 py-2 font-semibold">Категория</th>
              <th className="px-3 py-2 font-semibold">Капитал</th>
              <th className="px-3 py-2 font-semibold">Источник</th>
              <th className="px-3 py-2 font-semibold">Создан</th>
              <th className="px-3 py-2 font-semibold">Действие</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-qa-muted">
                  <Spinner size={18} className="mx-auto" />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-qa-muted">
                  Нет записей по выбранным фильтрам
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={row.id}
                  className={clsx(
                    "border-b border-cockpit-border/50 hover:bg-cockpit-panel-raised/30",
                    isFetching && "opacity-70",
                  )}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-qa-text truncate max-w-[220px]">
                      {row.contact_name || "—"}
                    </div>
                    <div className="text-qa-muted truncate max-w-[220px]">{row.contact_email}</div>
                  </td>
                  <td className="px-3 py-2">
                    <span className="uppercase text-[10px] font-semibold tracking-wide px-1.5 py-0.5 rounded border border-cockpit-border">
                      {BUCKET_LABELS[row.display_bucket || "trial"] || row.status}
                    </span>
                    {row.is_admin ? (
                      <span className="ml-1 text-[9px] uppercase text-terminal-accent">админ</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-terminal-accent/90">{row.capital_range || "—"}</td>
                  <td className="px-3 py-2 text-qa-muted">{row.source}</td>
                  <td className="px-3 py-2 text-qa-muted tabular-nums whitespace-nowrap">
                    {format(parseISO(row.created_at), "dd.MM.yyyy HH:mm")}
                  </td>
                  <td className="px-3 py-2">
                    <AdmissionActionButtons
                      row={row}
                      disabled={pending}
                      onFullAccess={() => approveMut.mutate(row.id)}
                      onAdmin={() => adminMut.mutate(row.id)}
                      onRevokeAdmin={() => revokeAdminMut.mutate(row.id)}
                      onSuspend={() => suspendMut.mutate(row.id)}
                    />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="p-3 border-t border-cockpit-border flex items-center justify-between gap-2 shrink-0">
        <button
          type="button"
          className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-40"
          disabled={page <= 1 || isLoading}
          onClick={() => onPageChange(page - 1)}
        >
          ← Назад
        </button>
        <div className="flex items-center gap-1">
          {Array.from({ length: Math.min(pages, 7) }, (_, i) => {
            const start = Math.max(1, Math.min(page - 3, pages - 6));
            const pageNum = pages <= 7 ? i + 1 : start + i;
            if (pageNum < 1 || pageNum > pages) return null;
            return (
              <button
                key={pageNum}
                type="button"
                className={clsx(
                  "min-w-[2rem] px-2 py-1 rounded text-xs border",
                  pageNum === page
                    ? "border-terminal-accent bg-[var(--qa-active)] text-terminal-accent"
                    : "border-cockpit-border text-qa-muted hover:bg-cockpit-panel-raised/40",
                )}
                onClick={() => onPageChange(pageNum)}
              >
                {pageNum}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-40"
          disabled={page >= pages || isLoading}
          onClick={() => onPageChange(page + 1)}
        >
          Вперёд →
        </button>
      </div>
    </div>
  );
}
