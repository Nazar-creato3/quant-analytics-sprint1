"use client";

import { Suspense, useCallback, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertCircle } from "lucide-react";
import { ThemeLogo } from "@/components/shared/ThemeLogo";
import { PhoneCodeField } from "@/components/auth/PhoneCodeField";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { authApi } from "@/lib/api";

function safeNext(raw: string | null): string {
  // Only same-site paths: never redirect to another host.
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

function VerifyPhoneForm() {
  const params = useSearchParams();
  const [value, setValue] = useState<{ phone: string; code: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onChange = useCallback((v: { phone: string; code: string } | null) => setValue(v), []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      await authApi.confirmPhone(value.phone, value.code);
      window.location.href = safeNext(params.get("next"));
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Не удалось подтвердить номер");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="w-full max-w-sm">
      <div className="text-center mb-6">
        <div className="inline-flex mb-4">
          <ThemeLogo width={48} height={48} priority />
        </div>
        <h1 className="text-xl font-bold text-qa-text">Подтвердите номер телефона</h1>
        <p className="text-sm text-qa-muted mt-1">Вход в сервис доступен по подтверждённому российскому номеру.</p>
      </div>
      <form className="card p-6 space-y-4" onSubmit={submit}>
        <PhoneCodeField onChange={onChange} disabled={busy} />
        {error && (
          <div className="alert-error">
            <AlertCircle size={13} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
        <button type="submit" className="btn-primary w-full justify-center py-2.5" disabled={!value || busy}>
          {busy ? "Проверяю…" : "Подтвердить"}
        </button>
      </form>
      <LegalFooter />
    </div>
  );
}

export default function VerifyPhonePage() {
  return (
    <div className="min-h-screen bg-cockpit-bg flex items-center justify-center px-4">
      <Suspense fallback={<div className="text-sm text-qa-muted">Загрузка…</div>}>
        <VerifyPhoneForm />
      </Suspense>
    </div>
  );
}
