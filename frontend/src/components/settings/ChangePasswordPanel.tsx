"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { KeyRound } from "lucide-react";
import { toast } from "react-hot-toast";
import { authApi } from "@/lib/api";

type Step = "form" | "confirm" | "done";

export function ChangePasswordPanel() {
  const searchParams = useSearchParams();
  const [step, setStep] = useState<Step>("form");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");

  useEffect(() => {
    const token = searchParams.get("password_token");
    if (token) {
      setStep("confirm");
    }
  }, [searchParams]);

  const requestMutation = useMutation({
    mutationFn: () => authApi.requestPasswordChange(newPassword, confirmPassword),
    onSuccess: (data) => {
      setStep("confirm");
      if (data.dev_code) {
        toast.success(`Код отправлен (dev): ${data.dev_code}`);
      } else {
        toast.success("Код подтверждения отправлен на ваш email");
      }
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Не удалось отправить код");
    },
  });

  const confirmMutation = useMutation({
    mutationFn: () => {
      const token = searchParams.get("password_token");
      return authApi.confirmPasswordChange({
        newPassword,
        confirmPassword,
        code: code || undefined,
        token: token || undefined,
      });
    },
    onSuccess: () => {
      setStep("done");
      toast.success("Пароль успешно изменён. Войдите снова.");
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Неверный или просроченный код");
    },
  });

  if (step === "done") {
    return (
      <section className="page-section">
        <div className="flex items-center gap-2 mb-3">
          <KeyRound size={16} className="text-terminal-up" />
          <h2 className="page-section-title mb-0">Смена пароля</h2>
        </div>
        <p className="text-sm text-terminal-up">Пароль обновлён. Перезайдите в аккаунт.</p>
      </section>
    );
  }

  return (
    <section className="page-section">
      <div className="flex items-center gap-2 mb-1">
        <KeyRound size={16} className="text-terminal-accent" />
        <h2 className="page-section-title mb-0">Смена пароля</h2>
      </div>
      <p className="page-section-desc mb-4">
        Новый пароль применится только после подтверждения кодом из email, указанного в профиле.
      </p>

      {step === "form" ? (
        <div className="space-y-4 max-w-md">
          <div>
            <label className="label" htmlFor="qa-new-password">Новый пароль</label>
            <input
              id="qa-new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="input w-full"
              minLength={12}
              autoComplete="new-password"
            />
          </div>
          <div>
            <label className="label" htmlFor="qa-confirm-password">Подтверждение пароля</label>
            <input
              id="qa-confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="input w-full"
              minLength={12}
              autoComplete="new-password"
            />
          </div>
          <p className="text-xs text-terminal-muted mb-2">
            Минимум 12 символов в обоих полях.
          </p>
          <button
            type="button"
            onClick={() => {
              if (newPassword.length < 12 || confirmPassword.length < 12) {
                toast.error("Пароль должен быть не короче 12 символов");
                return;
              }
              if (newPassword !== confirmPassword) {
                toast.error("Пароли не совпадают");
                return;
              }
              requestMutation.mutate();
            }}
            disabled={requestMutation.isPending}
            className="btn-primary"
          >
            {requestMutation.isPending ? "Отправка…" : "Отправить код на email"}
          </button>
        </div>
      ) : (
        <div className="space-y-4 max-w-md">
          <div>
            <label className="label" htmlFor="qa-new-password-confirm-step">Новый пароль</label>
            <input
              id="qa-new-password-confirm-step"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="input w-full"
              minLength={12}
              autoComplete="new-password"
            />
          </div>
          <div>
            <label className="label" htmlFor="qa-confirm-password-confirm-step">Подтверждение пароля</label>
            <input
              id="qa-confirm-password-confirm-step"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="input w-full"
              minLength={12}
              autoComplete="new-password"
            />
          </div>
          {!searchParams.get("password_token") && (
            <div>
              <label className="label" htmlFor="qa-password-email-code">Код из email (6 цифр)</label>
              <input
                id="qa-password-email-code"
                type="text"
                inputMode="numeric"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                className="input w-full font-mono tracking-widest"
                maxLength={6}
                placeholder="000000"
              />
            </div>
          )}
          <button
            type="button"
            onClick={() => confirmMutation.mutate()}
            disabled={
              confirmMutation.isPending ||
              newPassword.length < 12 ||
              newPassword !== confirmPassword ||
              (!code && !searchParams.get("password_token"))
            }
            className="btn-primary"
          >
            {confirmMutation.isPending ? "Сохранение…" : "Подтвердить смену пароля"}
          </button>
          <button
            type="button"
            onClick={() => setStep("form")}
            className="btn-secondary ml-2"
          >
            Назад
          </button>
        </div>
      )}
    </section>
  );
}
