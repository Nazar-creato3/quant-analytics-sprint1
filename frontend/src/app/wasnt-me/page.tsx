"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authApi } from "@/lib/api";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { AlertCircle, ShieldAlert } from "lucide-react";

function WasntMeContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";
  const [status, setStatus] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Ссылка недействительна — отсутствует токен");
      return;
    }
    let cancelled = false;
    (async () => {
      setStatus("loading");
      try {
        const res = await authApi.reportUnauthorizedPasswordChange(token);
        if (cancelled) return;
        setStatus("ok");
        setMessage(res.message);
      } catch (err: unknown) {
        if (cancelled) return;
        setStatus("error");
        setMessage(err instanceof Error ? err.message : "Не удалось обработать запрос");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="w-full max-w-sm">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-xl bg-terminal-down/10 border border-terminal-down/40 mb-4">
          <ShieldAlert size={28} className="text-terminal-down" />
        </div>
        <h1 className="text-2xl font-bold text-qa-text tracking-tight">Это были не вы?</h1>
        <p className="text-sm text-qa-muted mt-1">Отзываем все активные сессии</p>
      </div>

      <div className="card p-6 space-y-4">
        {status === "loading" && <p className="text-sm text-qa-muted">Обработка…</p>}
        {status === "ok" && (
          <p className="text-sm text-terminal-up">{message ?? "Все сессии отозваны. Аккаунт помечен для проверки."}</p>
        )}
        {status === "error" && (
          <div className="flex items-start gap-2 text-terminal-down text-sm">
            <AlertCircle size={16} className="shrink-0 mt-0.5" />
            <span>{message}</span>
          </div>
        )}
        <Link href="/login" className="block text-center text-sm text-primary hover:text-accent">
          Перейти ко входу
        </Link>
      </div>
    </div>
  );
}

export default function WasntMePage() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-12 bg-qa-bg">
      <Suspense fallback={<p className="text-qa-muted text-sm">Загрузка…</p>}>
        <WasntMeContent />
      </Suspense>
      <div className="mt-12 w-full max-w-md"><LegalFooter /></div>
    </main>
  );
}
