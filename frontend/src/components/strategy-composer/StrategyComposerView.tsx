"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "react-hot-toast";
import { clsx } from "clsx";
import {
  GitBranch, GripVertical, Play, RefreshCw, Save, ShieldCheck, Trash2, Workflow,
} from "lucide-react";
import { NavBar } from "@/components/layout/NavBar";
import { CrossActions } from "@/components/shared/CrossActions";
import { useProductContext } from "@/contexts/ProductContext";
import { queryKeys } from "@/lib/queryKeys";
import { Spinner, Tooltip } from "@/components/ui";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { strategyComposerApi } from "@/lib/api";
import { ComposerBacktestPanel } from "@/components/strategy-composer/ComposerBacktestPanel";
import type {
  ComposerBranch,
  ComposerConfig,
  ComposerOutcome,
  ComposerPredicate,
  ComposerValidationResult,
  CompiledStrategyConfig,
} from "@/types";

function ComposerContextLine() {
  const { activeTicker } = useProductContext();
  return (
    <div className="px-4 py-2 border-b border-cockpit-border">
      <CrossActions ticker={activeTicker} />
    </div>
  );
}

const BLOCK_PALETTE = [
  {
    type: "predicate",
    label: "Условие",
    desc: "Фильтр по volatility, regime или session — когда правило срабатывает",
  },
  {
    type: "branch",
    label: "Ветка",
    desc: "If / Else маршрут: при выполнении условий → outcome или другая ветка",
  },
  {
    type: "outcome",
    label: "Strategy Outcome",
    desc: "Итоговая стратегия: Grid, Trend, Mean Reversion и др.",
  },
] as const;

function uid(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

function PredicateEditor({
  predicate,
  onChange,
  onRemove,
}: {
  predicate: ComposerPredicate;
  onChange: (next: ComposerPredicate) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 bg-cockpit-panel-raised border border-cockpit-border rounded px-2 py-1.5">
      <GripVertical size={12} className="text-qa-muted shrink-0" />
      <select
        value={predicate.field}
        onChange={(e) => onChange({ ...predicate, field: e.target.value as ComposerPredicate["field"] })}
        className="bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
      >
        <option value="volatility_percentile">перцентиль волатильности</option>
        <option value="volatility">волатильность</option>
        <option value="regime">режим рынка</option>
        <option value="microstructure_score">качество стакана</option>
        <option value="session_active">торговая сессия идёт</option>
      </select>
      <select
        value={predicate.operator}
        onChange={(e) => onChange({ ...predicate, operator: e.target.value as ComposerPredicate["operator"] })}
        className="bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
      >
        <option value="gt">&gt;</option>
        <option value="gte">&gt;=</option>
        <option value="lt">&lt;</option>
        <option value="lte">&lt;=</option>
        <option value="eq">==</option>
        <option value="neq">!=</option>
        <option value="in">входит в</option>
      </select>
      {predicate.field === "session_active" ? (
        <select
          value={String(predicate.value)}
          onChange={(e) => onChange({ ...predicate, value: e.target.value === "true" })}
          className="bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
        >
          <option value="true">да</option>
          <option value="false">нет</option>
        </select>
      ) : predicate.field === "regime" ? (
        <select
          value={String(predicate.value)}
          onChange={(e) => onChange({ ...predicate, value: e.target.value })}
          className="bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
        >
          <option value="trend">тренд</option>
          <option value="trend_up">рост</option>
          <option value="trend_down">падение</option>
          <option value="range">боковик</option>
          <option value="high_vol">высокая волатильность</option>
          <option value="low_vol">низкая волатильность</option>
          <option value="unknown">нет данных</option>
          <option value="range_bound">в диапазоне</option>
        </select>
      ) : (
        <input
          type="number"
          step="0.05"
          min={0}
          max={1}
          value={Number(predicate.value)}
          onChange={(e) => onChange({ ...predicate, value: parseFloat(e.target.value) || 0 })}
          className="w-20 bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
        />
      )}
      <button type="button" onClick={onRemove} className="text-qa-muted hover:text-terminal-down ml-auto">
        <Trash2 size={12} />
      </button>
    </div>
  );
}

function OutcomeCard({
  outcome,
  onChange,
  onRemove,
}: {
  outcome: ComposerOutcome;
  onChange: (next: ComposerOutcome) => void;
  onRemove: () => void;
}) {
  return (
    <div className="cockpit-panel p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="cockpit-panel-header">Итог (Outcome)</span>
        <button type="button" onClick={onRemove} className="text-qa-muted hover:text-terminal-down">
          <Trash2 size={12} />
        </button>
      </div>
      <input
        value={outcome.label}
        onChange={(e) => onChange({ ...outcome, label: e.target.value })}
        className="w-full bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-xs"
        placeholder="Название outcome"
      />
      <select
        value={outcome.primary_strategy}
        onChange={(e) =>
          onChange({
            ...outcome,
            primary_strategy: e.target.value,
            grid_mode: e.target.value === "grid" ? outcome.grid_mode ?? "point" : null,
          })
        }
        className="w-full bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
      >
        {["grid", "trend", "mean_reversion", "breakout", "hedge", "income", "rotation", "volatility_harvesting"].map(
          (s) => (
            <option key={s} value={s}>{s}</option>
          ),
        )}
      </select>
      {outcome.primary_strategy === "grid" && (
        <select
          value={outcome.grid_mode ?? "point"}
          onChange={(e) => onChange({ ...outcome, grid_mode: e.target.value })}
          className="w-full bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
        >
          <option value="point">point</option>
          <option value="diversified">diversified</option>
        </select>
      )}
      <div className="text-[10px] font-mono text-qa-muted">{outcome.id}</div>
    </div>
  );
}

function BranchBlock({
  branch,
  outcomes,
  branches,
  isRoot,
  onChange,
  onRemove,
  onSetRoot,
}: {
  branch: ComposerBranch;
  outcomes: ComposerOutcome[];
  branches: ComposerBranch[];
  isRoot: boolean;
  onChange: (next: ComposerBranch) => void;
  onRemove: () => void;
  onSetRoot: () => void;
}) {
  const updatePredicate = (index: number, next: ComposerPredicate) => {
    const predicates = [...branch.condition.predicates];
    predicates[index] = next;
    onChange({
      ...branch,
      condition: { ...branch.condition, predicates },
    });
  };

  const removePredicate = (index: number) => {
    const predicates = branch.condition.predicates.filter((_, i) => i !== index);
    onChange({
      ...branch,
      condition: { ...branch.condition, predicates },
    });
  };

  const addPredicate = () => {
    onChange({
      ...branch,
      condition: {
        ...branch.condition,
        predicates: [
          ...branch.condition.predicates,
          { field: "volatility_percentile", operator: "gt", value: 0.5 },
        ],
      },
    });
  };

  return (
    <div
      className={clsx(
        "cockpit-panel p-3 space-y-3 border-l-2",
        isRoot ? "border-l-terminal-up" : "border-l-terminal-accent",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <GitBranch size={14} className={isRoot ? "text-terminal-up" : "text-terminal-accent"} />
          <span className="text-xs font-semibold uppercase tracking-wide">
            {isRoot ? "Корневая ветка" : "Ветка"}
          </span>
          {isRoot && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-qa-success-bg text-terminal-up border border-terminal-up/40">
              entry
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!isRoot && (
            <button type="button" onClick={onSetRoot} className="cockpit-action-btn text-[10px]">
              Сделать корневой
            </button>
          )}
          <button type="button" onClick={onRemove} className="text-qa-muted hover:text-terminal-down">
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase text-qa-muted">Логика</span>
        <select
          value={branch.condition.logic}
          onChange={(e) =>
            onChange({
              ...branch,
              condition: { ...branch.condition, logic: e.target.value as "and" | "or" },
            })
          }
          className="bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
        >
          <option value="and">AND</option>
          <option value="or">OR</option>
        </select>
      </div>

      <div className="space-y-2">
        {branch.condition.predicates.map((predicate, index) => (
          <PredicateEditor
            key={`${branch.id}-pred-${index}`}
            predicate={predicate}
            onChange={(next) => updatePredicate(index, next)}
            onRemove={() => removePredicate(index)}
          />
        ))}
        <button type="button" onClick={addPredicate} className="cockpit-action-btn w-full text-[10px]">
          + Добавить условие
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-2 border-t border-cockpit-border">
        <div>
          <label className="text-[10px] uppercase text-terminal-up block mb-1">Then → outcome</label>
          <select
            value={branch.then_outcome_id}
            onChange={(e) => onChange({ ...branch, then_outcome_id: e.target.value })}
            className="w-full bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
          >
            {outcomes.map((o) => (
              <option key={o.id} value={o.id}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] uppercase text-terminal-accent block mb-1">Else → outcome / ветка</label>
          <select
            value={branch.else_outcome_id ?? ""}
            onChange={(e) =>
              onChange({
                ...branch,
                else_outcome_id: e.target.value || null,
                else_branch_id: e.target.value ? null : branch.else_branch_id,
              })
            }
            className="w-full bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono mb-1"
          >
            <option value="">— другая ветка —</option>
            {outcomes.map((o) => (
              <option key={o.id} value={o.id}>{o.label}</option>
            ))}
          </select>
          {!branch.else_outcome_id && (
            <select
              value={branch.else_branch_id ?? ""}
              onChange={(e) =>
                onChange({
                  ...branch,
                  else_branch_id: e.target.value || null,
                  else_outcome_id: null,
                })
              }
              className="w-full bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
            >
              <option value="">Выберите ветку</option>
              {branches
                .filter((b) => b.id !== branch.id)
                .map((b) => (
                  <option key={b.id} value={b.id}>{b.id}</option>
                ))}
            </select>
          )}
        </div>
      </div>
    </div>
  );
}

export function StrategyComposerView() {
  const queryClient = useQueryClient();
  const { activeAccount, mode } = useProductContext();
  const [config, setConfig] = useState<ComposerConfig | null>(null);
  const [validation, setValidation] = useState<ComposerValidationResult | null>(null);
  const [compiled, setCompiled] = useState<CompiledStrategyConfig | null>(null);
  const [dragBlockType, setDragBlockType] = useState<string | null>(null);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: queryKeys.composer(activeAccount, mode),
    queryFn: strategyComposerApi.load,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (data) setConfig(data);
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: strategyComposerApi.save,
    onSuccess: (data) => {
      setConfig(data);
      queryClient.setQueryData(queryKeys.composer(activeAccount, mode), data);
      toast.success("Composer config сохранён в профиль");
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Save failed");
    },
  });

  const validateMutation = useMutation({
    mutationFn: strategyComposerApi.validate,
    onSuccess: (result) => {
      setValidation(result);
      toast.success(result.valid ? "Config valid" : "Validation failed");
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Validate failed");
    },
  });

  const compileMutation = useMutation({
    mutationFn: strategyComposerApi.compile,
    onSuccess: (result) => {
      setCompiled(result);
      toast.success("Compiled to strategy parameters");
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Compile failed");
    },
  });

  const updateConfig = useCallback((updater: (prev: ComposerConfig) => ComposerConfig) => {
    setConfig((prev) => (prev ? updater(prev) : prev));
    setValidation(null);
    setCompiled(null);
  }, []);

  const addBlock = useCallback(
    (type: string) => {
      if (!config) return;
      if (type === "predicate") {
        const root = config.branches.find((b) => b.id === config.root_branch_id);
        if (!root) return;
        updateConfig((prev) => ({
          ...prev,
          branches: prev.branches.map((b) =>
            b.id === prev.root_branch_id
              ? {
                  ...b,
                  condition: {
                    ...b.condition,
                    predicates: [
                      ...b.condition.predicates,
                      { field: "volatility_percentile", operator: "gt", value: 0.5 },
                    ],
                  },
                }
              : b,
          ),
        }));
      } else if (type === "branch") {
        const branchId = uid("branch");
        updateConfig((prev) => ({
          ...prev,
          branches: [
            ...prev.branches,
            {
              id: branchId,
              condition: {
                id: branchId,
                logic: "and",
                predicates: [{ field: "regime", operator: "eq", value: "range" }],
              },
              then_outcome_id: prev.outcomes[0]?.id ?? uid("outcome"),
              else_outcome_id: prev.default_outcome_id,
            },
          ],
        }));
      } else if (type === "outcome") {
        const outcomeId = uid("outcome");
        updateConfig((prev) => ({
          ...prev,
          outcomes: [
            ...prev.outcomes,
            {
              id: outcomeId,
              label: "New Outcome",
              primary_strategy: "mean_reversion",
            },
          ],
        }));
      }
    },
    [config, updateConfig],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (dragBlockType) addBlock(dragBlockType);
      setDragBlockType(null);
    },
    [addBlock, dragBlockType],
  );

  const rootBranch = useMemo(
    () => config?.branches.find((b) => b.id === config.root_branch_id),
    [config],
  );

  if (isLoading || !config) {
    return (
      <div className="min-h-screen bg-cockpit-bg operator-shell flex items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="composer" />
      <ComposerContextLine />

      <div className="border-b border-cockpit-border bg-cockpit-surface px-4 py-2 shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Workflow size={14} className="text-terminal-up" />
          <span className="text-xs font-bold uppercase tracking-wide">Конструктор стратегий</span>
          <span className="text-[10px] text-qa-muted font-mono">no-code · StrategyMesh</span>
        </div>
        <div className="flex items-center gap-2">
          <Tooltip tip="Перезагрузить профиль с сервера (сброс несохранённых правок)">
            <button
              type="button"
              onClick={async () => {
                const result = await refetch();
                if (result.data) {
                  setConfig(result.data);
                  setValidation(null);
                  setCompiled(null);
                  toast.success("Конфигурация перезагружена с сервера");
                } else {
                  toast.error("Не удалось перезагрузить конфигурацию");
                }
              }}
              disabled={isFetching}
              className="cockpit-action-btn text-qa-text"
            >
              <RefreshCw size={11} className={isFetching ? "animate-spin" : undefined} />
              Обновить
            </button>
          </Tooltip>
          <Tooltip tip="Проверить логику веток и ссылки на outcomes без сохранения">
            <button
              type="button"
              onClick={() => {
                if (!config) return;
                validateMutation.mutate(config);
              }}
              disabled={validateMutation.isPending || !config}
              className="cockpit-action-btn text-terminal-accent"
            >
              <ShieldCheck size={11} />
              Проверить
            </button>
          </Tooltip>
          <Tooltip tip="Скомпилировать блок-схему в параметры стратегии для бота">
            <button
              type="button"
              onClick={() => {
                if (!config) return;
                compileMutation.mutate(config);
              }}
              disabled={compileMutation.isPending || !config}
              className="cockpit-action-btn text-terminal-accent"
            >
              <Play size={11} />
              Собрать
            </button>
          </Tooltip>
          <Tooltip tip="Сохранить текущую схему в профиль пользователя">
            <button
              type="button"
              onClick={() => {
                if (!config) return;
                saveMutation.mutate(config);
              }}
              disabled={saveMutation.isPending || !config}
              className="cockpit-action-btn text-terminal-up"
            >
              <Save size={11} />
              Сохранить профиль
            </button>
          </Tooltip>
        </div>
      </div>

      <main className="flex-1 overflow-auto p-3 lg:p-4">
        <ErrorBoundary>
        <div className="max-w-[1600px] mx-auto grid grid-cols-1 xl:grid-cols-[240px_1fr_320px] gap-3">
          {/* Palette */}
          <aside className="space-y-3">
            <div className="cockpit-panel p-3">
              <div className="cockpit-panel-header mb-3">Палитра блоков</div>
              <div className="space-y-2">
                {BLOCK_PALETTE.map((block) => (
                  <div
                    key={block.type}
                    draggable
                    onDragStart={() => setDragBlockType(block.type)}
                    onDragEnd={() => setDragBlockType(null)}
                    className="flex items-start gap-2 p-2 rounded border border-cockpit-border bg-cockpit-panel-raised cursor-grab active:cursor-grabbing hover:border-terminal-up/40"
                  >
                    <GripVertical size={12} className="text-qa-muted mt-0.5 shrink-0" />
                    <div>
                      <div className="text-[11px] font-semibold">{block.label}</div>
                      <div className="text-[10px] text-qa-muted">{block.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="cockpit-panel p-3">
              <div className="cockpit-panel-header mb-2">Конфигурация</div>
              <input
                value={config.name}
                onChange={(e) => updateConfig((prev) => ({ ...prev, name: e.target.value }))}
                className="w-full bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-xs mb-2"
              />
              <label className="text-[10px] uppercase text-qa-muted block mb-1">Outcome по умолчанию</label>
              <select
                value={config.default_outcome_id}
                onChange={(e) =>
                  updateConfig((prev) => ({ ...prev, default_outcome_id: e.target.value }))
                }
                className="w-full bg-cockpit-bg border border-cockpit-border rounded px-2 py-1 text-[11px] font-mono"
              >
                {config.outcomes.map((o) => (
                  <option key={o.id} value={o.id}>{o.label}</option>
                ))}
              </select>
            </div>
          </aside>

          {/* Canvas */}
          <section
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            className="space-y-3 min-h-[480px] rounded-lg border border-dashed border-cockpit-border p-3 bg-cockpit-surface/40"
          >
            <div className="text-[10px] uppercase tracking-wider text-qa-muted mb-1">
              Поток условий — перетащите блоки сюда
            </div>

            {rootBranch && (
              <BranchBlock
                branch={rootBranch}
                outcomes={config.outcomes}
                branches={config.branches}
                isRoot
                onChange={(next) =>
                  updateConfig((prev) => ({
                    ...prev,
                    branches: prev.branches.map((b) => (b.id === next.id ? next : b)),
                  }))
                }
                onRemove={() => toast.error("Cannot remove root branch")}
                onSetRoot={() => undefined}
              />
            )}

            {config.branches
              .filter((b) => b.id !== config.root_branch_id)
              .map((branch) => (
                <BranchBlock
                  key={branch.id}
                  branch={branch}
                  outcomes={config.outcomes}
                  branches={config.branches}
                  isRoot={false}
                  onChange={(next) =>
                    updateConfig((prev) => ({
                      ...prev,
                      branches: prev.branches.map((b) => (b.id === next.id ? next : b)),
                    }))
                  }
                  onRemove={() =>
                    updateConfig((prev) => ({
                      ...prev,
                      branches: prev.branches.filter((b) => b.id !== branch.id),
                      root_branch_id:
                        prev.root_branch_id === branch.id
                          ? prev.branches[0]?.id ?? prev.root_branch_id
                          : prev.root_branch_id,
                    }))
                  }
                  onSetRoot={() =>
                    updateConfig((prev) => ({ ...prev, root_branch_id: branch.id }))
                  }
                />
              ))}

            <div className="text-[11px] text-qa-muted font-mono border border-cockpit-border rounded p-3 bg-cockpit-bg">
              IF volatility &gt; X AND regime == trend THEN grid_mode ELSE mean_reversion
            </div>
          </section>

          {/* Outcomes + output */}
          <aside className="space-y-3">
            <div className="cockpit-panel p-3">
              <div className="cockpit-panel-header mb-3">Исходы стратегии</div>
              <div className="space-y-2">
                {config.outcomes.map((outcome) => (
                  <OutcomeCard
                    key={outcome.id}
                    outcome={outcome}
                    onChange={(next) =>
                      updateConfig((prev) => ({
                        ...prev,
                        outcomes: prev.outcomes.map((o) => (o.id === next.id ? next : o)),
                      }))
                    }
                    onRemove={() => {
                      if (config.outcomes.length <= 1) {
                        toast.error("At least one outcome required");
                        return;
                      }
                      updateConfig((prev) => ({
                        ...prev,
                        outcomes: prev.outcomes.filter((o) => o.id !== outcome.id),
                      }));
                    }}
                  />
                ))}
              </div>
            </div>

            {validation && (
              <div className="cockpit-panel p-3">
                <div className="cockpit-panel-header mb-2">Проверка</div>
                <div
                  className={clsx(
                    "text-xs font-semibold mb-2",
                    validation.valid ? "text-terminal-up" : "text-terminal-down",
                  )}
                >
                  {validation.valid ? "VALID" : "INVALID"}
                </div>
                {Array.isArray(validation.errors) && validation.errors.map((err) => (
                  <div key={err} className="text-[11px] text-terminal-down font-mono mb-1">{err}</div>
                ))}
                {Array.isArray(validation.warnings) && validation.warnings.map((warn) => (
                  <div key={warn} className="text-[11px] text-terminal-accent font-mono mb-1">{warn}</div>
                ))}
              </div>
            )}

            {compiled && (
              <div className="cockpit-panel p-3">
                <div className="cockpit-panel-header mb-2">Итоговая настройка</div>
                <pre className="text-[10px] font-mono text-qa-muted overflow-auto max-h-64 whitespace-pre-wrap">
                  {JSON.stringify(compiled, null, 2)}
                </pre>
              </div>
            )}

            <ComposerBacktestPanel config={config} />
          </aside>
        </div>
        </ErrorBoundary>
      </main>
    </div>
  );
}
