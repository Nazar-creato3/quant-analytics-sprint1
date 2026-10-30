"use client";

import { FormEvent, useState } from "react";
import { ThemeLogo } from "@/components/shared/ThemeLogo";
import Link from "next/link";
import { authApi } from "@/lib/api";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { AlertCircle, Mail } from "lucide-react";

export default function RecoverPage() {
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await authApi.requestPasswordRecovery(email.trim());
      setSent(true);
    } catch {
      setError("Не удалось отправить запрос. Попробуйте ещё раз.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-qa-bg px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center mb-4">
            <ThemeLogo width={56} height={56} priority />
          </div>
          <h1 className="text-2xl font-bold text-qa-text tracking-tight">Восстановление пароля</h1>
          <p className="text-sm text-qa-muted mt-1">Мы отправим инструкции, если аккаунт существует</p>
        </div>

        <div className="card p-6">
          {sent ? (
            <div className="text-center space-y-3">
              <p className="text-sm text-qa-text">
                Если аккаунт с этим email существует, мы отправили инструкции по сбросу пароля.
              </p>
              <Link href="/login" className="text-sm text-primary hover:text-accent">
                Вернуться ко входу
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <label className="block text-sm text-qa-muted" htmlFor="recover-email">
                Email
              </label>
              <div className="relative">
                <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
                <input
                  id="recover-email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-10 pr-3 py-2.5 rounded-lg bg-qa-panel-secondary border border-qa-border-strong text-qa-text"
                  placeholder="you@example.com"
                />
              </div>
              {error && (
                <div className="flex items-start gap-2 text-sm text-red-400">
                  <AlertCircle size={16} className="mt-0.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
              <button
                type="submit"
                disabled={isLoading || !email}
                className="w-full py-2.5 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {isLoading ? "Отправка…" : "Отправить инструкции"}
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
    </div>
  );
}
