"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { CrossActions } from "@/components/shared/CrossActions";
import { DataState } from "@/components/shared/DataState";
import { useProductContext } from "@/contexts/ProductContext";
import { forecastApi } from "@/lib/api";
import { InvestmentProfileNotice } from "@/components/profile/InvestmentProfileForm";
import { ManeuverCycleCard } from "@/components/act/ManeuverCycleCard";
import { ManeuverHistory } from "@/components/act/ManeuverHistory";
import { TargetBookPanel } from "@/components/act/TargetBookPanel";
import type { ManeuverCard } from "@/lib/maneuver-cycle";

export default function ActPage() {
  const { activeTicker, activeAccount, mode } = useProductContext();
  const qc = useQueryClient();
  const proposals = useQuery({
    queryKey: ["act-propose", activeAccount, mode],
    queryFn: () => forecastApi.actPropose(activeAccount, mode),
  });
  const journal = useQuery({
    queryKey: ["act-journal", activeAccount],
    queryFn: () => forecastApi.actJournal(activeAccount),
  });
  const history = useQuery({
    queryKey: ["act-maneuvers", activeAccount],
    queryFn: () => forecastApi.actManeuvers(),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["act-propose"] });
    void qc.invalidateQueries({ queryKey: ["act-journal"] });
    void qc.invalidateQueries({ queryKey: ["act-maneuvers"] });
  };
  const act = useMutation({
    mutationFn: (job: () => Promise<unknown>) => job(),
    onSuccess: refresh,
  });

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="direct-deals" />
      <AppPageShell
        title="Манёвры"
        description="Предложения по вашему портфелю. Каждое можно принять, изменить или отклонить."
      >
        <span className="sr-only" data-testid="cycle-ticker">{activeTicker}</span>
        <CrossActions />
        <InvestmentProfileNotice />
        <TargetBookPanel book={proposals.data?.target_book} />
        {(proposals.data?.skipped || []).length > 0 ? (
          <div className="cockpit-panel p-4 text-xs space-y-1" data-testid="act-skipped">
            <p className="uppercase tracking-wide text-qa-muted">Не построено</p>
            {(proposals.data?.skipped || []).map((row) => (
              <p key={String(row.kind)}>{String(row.kind)}: {String(row.reason)}</p>
            ))}
          </div>
        ) : null}
        <DataState loading={proposals.isLoading} error={proposals.isError} empty={Boolean(proposals.data?.empty) && !(proposals.data?.items || []).length} emptyText={proposals.data?.reason || "Нет манёвров"}>
          <div className="space-y-2">
            {(proposals.data?.items || []).map((item) => {
              const card = item as ManeuverCard;
              const id = String(card.id || "");
              return (
                <div key={id} className="space-y-1">
                  <ManeuverCycleCard
                    item={card}
                    busy={act.isPending}
                    onView={() => act.mutate(() => forecastApi.actDecide({ maneuver_id: id, action: "view" }))}
                    onEdit={(qty) => act.mutate(() => forecastApi.actDecide({ maneuver_id: id, action: "edit", edits: { qty } }))}
                    onApprove={() => act.mutate(() => forecastApi.actDecide({ maneuver_id: id, action: "approve", confirm: true }))}
                    onReject={(reason, note) =>
                      act.mutate(() => forecastApi.actDecide({ maneuver_id: id, action: "reject", reject_reason: reason, reject_note: note }))
                    }
                    onSend={() => act.mutate(() => forecastApi.actSend(id))}
                    onExecute={() => act.mutate(() => forecastApi.actExecute(id, "paper"))}
                    onClose={() => act.mutate(() => forecastApi.actClose(id))}
                  />
                  <button
                    type="button"
                    className="text-xs underline text-terminal-accent"
                    onClick={() => {
                      void forecastApi.actJournalPdf(id).then((blob) => {
                        const url = URL.createObjectURL(blob);
                        const link = document.createElement("a");
                        link.href = url;
                        link.download = `maneuver-${id}.pdf`;
                        link.click();
                        URL.revokeObjectURL(url);
                      });
                    }}
                  >
                    Скачать журнал
                  </button>
                </div>
              );
            })}
          </div>
        </DataState>
        <ManeuverHistory items={(history.data?.items || []) as ManeuverCard[]} />
        <div className="cockpit-panel p-4 text-xs">
          <p className="uppercase tracking-wide text-qa-muted mb-2">Журнал манёвров</p>
          {(journal.data?.items || []).length === 0 ? <p>нет данных</p> : null}
          {(journal.data?.items || []).map((row) => (
            <p key={row.hash}>{row.at} · {row.name}</p>
          ))}
        </div>
      </AppPageShell>
    </div>
  );
}
