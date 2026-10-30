"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock, Globe, Shield, Zap } from "lucide-react";

const ICONS = [Clock, Zap, Globe, Shield];

async function fetchContent() {
  const res = await fetch("/api/v1/tokenized-equities/content");
  if (!res.ok) throw new Error("Не удалось загрузить данные");
  return res.json();
}

export function TokenizedEquitiesOnboarding() {
  const { data, isLoading } = useQuery({
    queryKey: ["tokenized-equities-content"],
    queryFn: fetchContent,
  });

  if (isLoading) {
    return <p className="text-sm text-qa-muted">Загрузка…</p>;
  }

  const advantages = data?.advantages ?? [];

  return (
    <section className="card p-5 space-y-4 border border-emerald-500/20">
      <div>
        <h2 className="font-semibold text-lg">Американские акции через токены</h2>
        <p className="text-xs text-qa-muted mt-1">
          Отдельный способ доступа к американским акциям для резидентов РФ — не обход ограничений, а другая модель исполнения.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {advantages.map((item: { id: string; title: string; body: string }, i: number) => {
          const Icon = ICONS[i % ICONS.length];
          return (
            <div key={item.id} className="rounded-lg bg-white/5 p-3 space-y-1">
              <div className="flex items-center gap-2 text-emerald-400 text-sm font-medium">
                <Icon size={16} />
                {item.title}
              </div>
              <p className="text-xs text-qa-muted leading-relaxed">{item.body}</p>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-qa-muted border-t border-white/10 pt-3">
        Новые пользователи начинают в <strong className="text-emerald-400">учебном режиме</strong> — заявки
        моделируются по рыночным ценам без подключения площадки. Подключите счёт, когда будете готовы к реальным заявкам.
      </p>
    </section>
  );
}
