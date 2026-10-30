"use client";

import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Pencil } from "lucide-react";
import { forecastApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";
import { trackClientEvent } from "@/lib/product-analytics";
import { HORIZON_OPTIONS, RISK_TOLERANCE_OPTIONS } from "@/lib/actPreviewInputs";

type Form = {
  horizon: string;
  risk_tolerance: string;
  expected_return: string; // shown in %, stored as a fraction
  max_position_pct: string; // %
  max_crisis_loss_pct: string; // %
  banned_tickers: string;
  account_type: string;
  iis_type: string;
  qualified_investor: boolean;
};

const DEFAULTS: Form = {
  horizon: "3y",
  risk_tolerance: "moderate",
  expected_return: "8",
  max_position_pct: "20",
  max_crisis_loss_pct: "15",
  banned_tickers: "",
  account_type: "regular",
  iis_type: "",
  qualified_investor: false,
};

const toPct = (frac: unknown, fallback: string) => {
  const n = Number(frac);
  return Number.isFinite(n) && String(frac ?? "") !== "" ? String(+(n * 100).toFixed(2)) : fallback;
};
const toFrac = (pct: string) => {
  const n = Number(String(pct).replace(",", "."));
  return Number.isFinite(n) ? String(+(n / 100).toFixed(4)) : "";
};

function fromSaved(row: Record<string, unknown>): Form {
  const list = (v: unknown) => (Array.isArray(v) ? v.join(", ") : String(v ?? ""));
  return {
    ...DEFAULTS,
    horizon: String(row.horizon || DEFAULTS.horizon),
    risk_tolerance: String(row.risk_tolerance || DEFAULTS.risk_tolerance),
    expected_return: toPct(row.expected_return, DEFAULTS.expected_return),
    max_position_pct: toPct(row.max_position_pct, DEFAULTS.max_position_pct),
    max_crisis_loss_pct: toPct(row.max_crisis_loss_pct, DEFAULTS.max_crisis_loss_pct),
    banned_tickers: list(row.banned_tickers),
    account_type: String(row.account_type || "regular"),
    iis_type: String(row.iis_type ?? ""),
    qualified_investor: Boolean(row.qualified_investor),
  };
}

const label = (opts: readonly { value: string; label: string }[], v: string) => opts.find((o) => o.value === v)?.label ?? v;

const INPUT =
  "mt-1 w-full rounded-md border border-cockpit-border bg-cockpit-panel px-2.5 py-1.5 text-sm text-qa-text focus:border-terminal-accent focus:outline-none";

/** Saved profile query — shared by the form and the «profile needed» notice. */
export function useInvestmentProfile() {
  const { activeAccount } = useProductContext();
  return useQuery({
    queryKey: ["investment-profile", activeAccount],
    queryFn: () => forecastApi.investmentProfileGet(),
  });
}

/**
 * Investment profile (Указание Банка России № 5014-У). Filled once: once saved it
 * shows as a short summary with «Изменить»; the questionnaire opens only on demand.
 */
export function InvestmentProfileForm() {
  const { activeAccount, mode } = useProductContext();
  const qc = useQueryClient();
  const current = useInvestmentProfile();
  const saved = current.data && !current.data.empty ? (current.data as Record<string, unknown>) : null;
  const [form, setForm] = useState<Form>(DEFAULTS);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (saved) setForm(fromSaved(saved));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current.data]);

  const save = useMutation({
    mutationFn: () =>
      forecastApi.investmentProfileSave({
        user_id: activeAccount,
        mode,
        ...form,
        expected_return: toFrac(form.expected_return),
        max_position_pct: toFrac(form.max_position_pct),
        max_crisis_loss_pct: toFrac(form.max_crisis_loss_pct),
      }),
    onSuccess: () => {
      setEditing(false);
      void qc.invalidateQueries({ queryKey: ["investment-profile"] });
      void qc.invalidateQueries({ queryKey: ["act-propose"] });
      void trackClientEvent("profile_questionnaire_completed");
    },
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  const warnings = ((saved?.warnings as Array<{ code: string; text: string }> | undefined) || []).filter(Boolean);
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setForm((s) => ({ ...s, [k]: e.target.value }));

  if (current.isLoading) {
    return <section className="card p-5 text-xs text-qa-muted" data-testid="investment-profile">Загрузка…</section>;
  }

  if (saved && !editing) {
    return (
      <section id="investment-profile" className="card p-5 space-y-2" data-testid="investment-profile">
        <div className="flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-qa-text">
            <CheckCircle2 size={16} className="text-terminal-up" aria-hidden />
            Лимиты риска заданы
          </h2>
          <button type="button" className="btn-ghost text-xs inline-flex items-center gap-1" onClick={() => setEditing(true)}>
            <Pencil size={12} aria-hidden /> Изменить
          </button>
        </div>
        <p className="text-xs text-qa-muted" data-testid="profile-summary">
          {label(HORIZON_OPTIONS, form.horizon)} · риск {label(RISK_TOLERANCE_OPTIONS, form.risk_tolerance).toLowerCase()} ·
          не больше {form.max_position_pct}% в одной бумаге · допустимый кризисный убыток до {form.max_crisis_loss_pct}%
        </p>
        {warnings.length ? (
          <ul className="text-xs text-warning list-disc pl-4" data-testid="profile-warnings">
            {warnings.map((w) => (
              <li key={w.code}>{w.text}</li>
            ))}
          </ul>
        ) : null}
      </section>
    );
  }

  return (
    <section id="investment-profile" className="card p-5 space-y-3" data-testid="investment-profile">
      <div>
        <h2 className="text-sm font-semibold text-qa-text">Ваши лимиты риска</h2>
        <p className="text-xs text-qa-muted mt-1">
          Правила, которые задаёте вы: манёвры считаются в этих рамках, а платформа предупреждает, если портфель выходит за них.
        </p>
      </div>
      <form className="grid gap-3 md:grid-cols-2 text-xs" onSubmit={onSubmit}>
        <label className="block">
          Горизонт инвестиций
          <select className={INPUT} value={form.horizon} onChange={set("horizon")}>
            {HORIZON_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="block">
          Готовность к риску
          <select className={INPUT} value={form.risk_tolerance} onChange={set("risk_tolerance")}>
            {RISK_TOLERANCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="block">
          Ожидаемая доходность, % в год
          <input className={INPUT} inputMode="decimal" value={form.expected_return} onChange={set("expected_return")} />
        </label>
        <label className="block">
          Максимум в одной бумаге, % портфеля
          <input className={INPUT} inputMode="decimal" value={form.max_position_pct} onChange={set("max_position_pct")} />
        </label>
        <label className="block">
          Допустимый убыток в кризис, %
          <input className={INPUT} inputMode="decimal" value={form.max_crisis_loss_pct} onChange={set("max_crisis_loss_pct")} />
        </label>
        <label className="block">
          Тип счёта
          <select className={INPUT} value={form.account_type} onChange={set("account_type")}>
            <option value="regular">брокерский счёт</option>
            <option value="iis">ИИС</option>
          </select>
        </label>
        <label className="block">
          Бумаги, которые не покупать
          <input className={INPUT} placeholder="например: GAZP, TSLA" value={form.banned_tickers} onChange={set("banned_tickers")} />
        </label>
        <label className="flex items-center gap-2 md:col-span-2">
          <input
            type="checkbox"
            checked={form.qualified_investor}
            onChange={(e) => setForm((s) => ({ ...s, qualified_investor: e.target.checked }))}
          />
          Я квалифицированный инвестор
        </label>
        <div className="md:col-span-2 flex gap-2">
          <button type="submit" className="btn-primary text-xs" data-testid="profile-save" disabled={save.isPending}>
            {save.isPending ? "Сохраняем…" : "Сохранить лимиты"}
          </button>
          {saved ? (
            <button type="button" className="btn-ghost text-xs" onClick={() => setEditing(false)}>
              Отмена
            </button>
          ) : null}
        </div>
        {save.isError ? <p className="md:col-span-2 text-terminal-down">Не удалось сохранить. Проверьте поля и попробуйте ещё раз.</p> : null}
      </form>
    </section>
  );
}

/** For pages that need the profile (manoeuvres): a short notice with a link to the cabinet. */
export function InvestmentProfileNotice() {
  const current = useInvestmentProfile();
  if (current.isLoading || (current.data && !current.data.empty)) return null;
  return (
    <div className="rounded-lg border border-terminal-accent/40 bg-terminal-accent/10 px-4 py-3 text-xs flex flex-wrap items-center justify-between gap-2" data-testid="profile-needed">
      <span>Задайте свои лимиты риска — манёвры будут считаться в этих рамках.</span>
      <a href="/account#investment-profile" className="btn-primary text-xs">
        Заполнить в кабинете
      </a>
    </div>
  );
}
