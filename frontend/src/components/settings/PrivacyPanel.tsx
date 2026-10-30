"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { forecastApi } from "@/lib/api";
import { DataState } from "@/components/shared/DataState";

export function PrivacyPanel() {
  const mapQuery = useQuery({
    queryKey: ["privacy-map"],
    queryFn: () => forecastApi.privacyMap(),
  });
  const exportMut = useMutation({
    mutationFn: () => forecastApi.privacyExport(),
  });
  const eraseMut = useMutation({
    mutationFn: () => forecastApi.privacyErase(),
  });

  return (
    <section className="rounded-xl border border-qa-border bg-qa-card p-4 space-y-3">
      <h2 className="text-sm font-semibold text-qa-text">Персональные данные</h2>
      <p className="text-xs text-qa-muted">
        Выгрузка без секретов. Удаление снимает журнал действий и профиль. Внешняя модель выключена.
      </p>
      <DataState
        loading={mapQuery.isLoading}
        error={mapQuery.isError}
        empty={Boolean(mapQuery.data && !mapQuery.data.items.length)}
      >
        {mapQuery.data?.items.length ? (
          <ul className="text-xs text-qa-text space-y-1">
            {mapQuery.data.items.map((row) => (
              <li key={row.data}>
                <span className="font-medium">{row.data}</span> — {row.store}
              </li>
            ))}
          </ul>
        ) : (
          <span className="sr-only">карта данных</span>
        )}
      </DataState>
      <div className="flex gap-2">
        <button type="button" className="btn-secondary text-xs" onClick={() => exportMut.mutate()}>
          Выгрузить
        </button>
        <button type="button" className="btn-secondary text-xs" onClick={() => eraseMut.mutate()}>
          Удалить мои данные
        </button>
      </div>
      {exportMut.data ? (
        <p className="text-xs text-qa-muted">
          Выгрузка: секреты не включены ({String(exportMut.data.secrets_included)}).
        </p>
      ) : null}
      {eraseMut.data?.erased ? <p className="text-xs text-qa-muted">Данные учёта удалены.</p> : null}
      <DataState loading={false} error={exportMut.isError || eraseMut.isError} empty={false}>
        <span className="sr-only">статус запроса</span>
      </DataState>
    </section>
  );
}
