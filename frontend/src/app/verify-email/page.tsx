"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { ThemeLogo } from "@/components/shared/ThemeLogo";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authApi } from "@/lib/api";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { AlertCircle, CheckCircle2, Mail } from "lucide-react";

function VerifyEmailForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "confirmed" | "resent">("idle");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      setIsLoading(true);
      try {
        await authApi.confirmEmailVerification(token);
        if (!cancelled) setStatus("confirmed");
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Ссылка недействительна или просрочена");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleResend = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await authApi.requestEmailVerification(email.trim());
      setStatus("resent");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Не удалось отправить письмо");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full max-w-sm">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center mb-4">
          <ThemeLogo width={56} height={56} priority />
        </div>
        <h1 className="text-2xl font-bold text-qa-text tracking-tight">Подтверждение email</h1>
      </div>

      <div className="card p-6 space-y-4">
        {isLoading && status === "idle" && token && (
          <p className="text-sm text-qa-muted text-center">Проверяем ссылку…</p>
        )}

        {status === "confirmed" && (
          <div className="text-center space-y-3">
            <CheckCircle2 className="mx-auto text-green-400" size={32} />
            <p className="text-sm text-qa-text">Email подтверждён. Можно войти в платформу.</p>
            <Link href="/login" className="text-sm text-primary hover:text-accent">
              Перейти ко входу
            </Link>
          </div>
        )}

        {status === "resent" && (
          <p className="text-sm text-qa-text text-center">
            Если аккаунт существует и не подтверждён, мы отправили новое письмо.
          </p>
        )}

        {!token && status !== "confirmed" && (
          <form onSubmit={handleResend} className="space-y-4">
            <p className="text-sm text-qa-muted">Запросите новую ссылку подтверждения</p>
            <div className="relative">
              <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full pl-10 pr-3 py-2.5 rounded-lg bg-qa-panel-secondary border border-qa-border-strong text-qa-text"
                placeholder="you@example.com"
              />
            </div>
            <button
              type="submit"
              disabled={isLoading || !email}
              className="w-full py-2.5 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {isLoading ? "Отправка…" : "Отправить ссылку"}
            </button>
          </form>
        )}

        {error && (
          <div className="flex items-start gap-2 text-sm text-red-400">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {error && token && (
          <form onSubmit={handleResend} className="space-y-3 pt-2 border-t border-qa-border-strong">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg bg-qa-panel-secondary border border-qa-border-strong text-qa-text"
              placeholder="Email для повторной отправки"
            />
            <button type="submit" disabled={isLoading || !email} className="w-full py-2 text-sm text-primary">
              Отправить новую ссылку
            </button>
          </form>
        )}
      </div>

      <p className="text-center text-xs text-qa-muted mt-6">
        <Link href="/login" className="text-primary hover:text-accent">
          Назад ко входу
        </Link>
      </p>
      <LegalFooter />
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-qa-bg px-4">
      <Suspense fallback={<div className="text-qa-muted text-sm">Загрузка…</div>}>
        <VerifyEmailForm />
      </Suspense>
    </div>
  );
}
