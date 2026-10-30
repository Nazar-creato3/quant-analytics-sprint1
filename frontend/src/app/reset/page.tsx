"use client";

import { FormEvent, Suspense, useState } from "react";
import { ThemeLogo } from "@/components/shared/ThemeLogo";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { authApi } from "@/lib/api";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { AlertCircle, Eye, EyeOff, Lock } from "lucide-react";

function ResetForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token") || "";

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (newPassword !== confirmPassword) {
      setError("Пароли не совпадают");
      return;
    }
    if (!token) {
      setError("Ссылка недействительна — отсутствует токен");
      return;
    }
    setIsLoading(true);
    try {
      await authApi.resetPassword({ token, newPassword, confirmPassword });
      router.push("/login?reset=1");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Не удалось сменить пароль");
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
        <h1 className="text-2xl font-bold text-qa-text tracking-tight">Новый пароль</h1>
        <p className="text-sm text-qa-muted mt-1">Минимум 12 символов</p>
      </div>

      <div className="card p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block text-sm text-qa-muted" htmlFor="new-password">
            Новый пароль
          </label>
          <div className="relative">
            <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
            <input
              id="new-password"
              type={showPassword ? "text" : "password"}
              required
              minLength={12}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full pl-10 pr-10 py-2.5 rounded-lg bg-qa-panel-secondary border border-qa-border-strong text-qa-text"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-qa-muted"
              aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>

          <label className="block text-sm text-qa-muted" htmlFor="confirm-password">
            Подтвердите пароль
          </label>
          <input
            id="confirm-password"
            type={showPassword ? "text" : "password"}
            required
            minLength={12}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-qa-panel-secondary border border-qa-border-strong text-qa-text"
          />

          {error && (
            <div className="flex items-start gap-2 text-sm text-red-400">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading || !newPassword || !confirmPassword}
            className="w-full py-2.5 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 disabled:opacity-50"
          >
            {isLoading ? "Сохранение…" : "Сохранить пароль"}
          </button>
        </form>
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

export default function ResetPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-qa-bg px-4">
      <Suspense fallback={<div className="text-qa-muted text-sm">Загрузка…</div>}>
        <ResetForm />
      </Suspense>
    </div>
  );
}
