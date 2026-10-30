"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { ThemeLogo } from "@/components/shared/ThemeLogo";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { authApi } from "@/lib/api";
import { RegistrationConsents, consentsGiven } from "@/components/auth/RegistrationConsents";
import { PhoneCodeField } from "@/components/auth/PhoneCodeField";
import { getBrowserFingerprint } from "@/lib/device-fingerprint";
import { isPublicSignupEnabled } from "@/lib/origination-public";
import {
  clearLegacyCredentialStorage,
  stripSensitiveLoginQueryParams,
  urlHasSensitiveLoginQueryParams,
} from "@/lib/login-security";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { markOnboardingOffer } from "@/lib/onboarding/storage";
import { clsx } from "clsx";
import { Eye, EyeOff, Lock, Mail, AlertCircle, User } from "lucide-react";

function SignupForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldsLocked, setFieldsLocked] = useState(true);
  const [consents, setConsents] = useState({ acceptTerms: false, consentPd: false });
  const [phone, setPhone] = useState<{ phone: string; code: string } | null>(null);
  const onPhone = useCallback((v: { phone: string; code: string } | null) => setPhone(v), []);

  useEffect(() => {
    clearLegacyCredentialStorage();
    if (typeof window !== "undefined" && urlHasSensitiveLoginQueryParams(window.location.href)) {
      const safe = stripSensitiveLoginQueryParams(new URL(window.location.href));
      window.history.replaceState(null, "", `${safe.pathname}${safe.search}${safe.hash}`);
    }
    const invite = searchParams.get("invite") === "1";
    if (!isPublicSignupEnabled() && !invite) {
      router.replace("/apply");
      return;
    }
    const unlock = window.setTimeout(() => setFieldsLocked(false), 100);
    return () => window.clearTimeout(unlock);
  }, [router, searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      const fingerprint = await getBrowserFingerprint();
      await authApi.register({
        email: email.trim(),
        password,
        accept_terms: consents.acceptTerms,
        consent_pd: consents.consentPd,
        fingerprint,
        user_agent: navigator.userAgent,
        contact_name: name.trim() || undefined,
        phone: phone?.phone,
        phone_code: phone?.code,
      });
      markOnboardingOffer();
      window.location.href = "/connect-capital";
    } catch (err: any) {
      const raw =
        err?.response?.data?.detail ||
        err?.message ||
        "Ошибка регистрации";
      const msg =
        raw === "Network Error"
          ? "Не удалось связаться с сервером. Проверьте соединение."
          : raw;
      setError(
        msg === "Email already registered"
          ? "Этот адрес уже зарегистрирован. Войдите или восстановите доступ."
          : msg === "max_accounts_per_device"
            ? "На этом устройстве уже есть аккаунт. Войдите в него или используйте другое устройство."
            : typeof raw === "string" && /[А-Яа-яЁё]/.test(raw)
              ? raw
              : "Не удалось зарегистрироваться.",
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full max-w-sm relative">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center mb-4">
          <ThemeLogo width={56} height={56} priority />
        </div>
          <h1 className="text-2xl font-bold text-qa-text tracking-tight">Регистрация</h1>
          <p className="text-sm text-qa-muted mt-1">
            Сразу откроется учебный режим: графики, расчёты и виртуальный счёт.
          </p>
      </div>

      <div className="card p-6">
        <form onSubmit={handleSubmit} className="space-y-4" autoComplete="off">
          <div>
            <label className="label" htmlFor="signup-name">
              Имя (необязательно)
            </label>
            <div className="relative">
              <User
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted"
              />
              <input
                id="signup-name"
                name="signup-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onFocus={() => setFieldsLocked(false)}
                readOnly={fieldsLocked}
                placeholder="Иван Иванов"
                autoComplete="off"
                className="input pl-9"
              />
            </div>
          </div>

          <div>
            <label className="label" htmlFor="signup-email">
              Email
            </label>
            <div className="relative">
              <Mail
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted"
              />
              <input
                id="signup-email"
                name="signup-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={() => setFieldsLocked(false)}
                readOnly={fieldsLocked}
                placeholder="you@example.com"
                required
                autoComplete="off"
                className="input pl-9"
              />
            </div>
          </div>

          <div>
            <label className="label" htmlFor="signup-password">
              Пароль (мин. 8 символов)
            </label>
            <div className="relative">
              <Lock
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted"
              />
              <input
                id="signup-password"
                name="signup-password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setFieldsLocked(false)}
                readOnly={fieldsLocked}
                placeholder="••••••••"
                required
                minLength={8}
                autoComplete="new-password"
                className="input pl-9 pr-9"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-qa-muted hover:text-qa-text transition-colors"
              >
                {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <PhoneCodeField onChange={onPhone} disabled={isLoading} />

          <RegistrationConsents value={consents} onChange={setConsents} />

          {error && (
            <div className="alert-error">
              <AlertCircle size={13} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading || !email || password.length < 8 || !phone || !consentsGiven(consents)}
            className={clsx(
              "btn-primary w-full justify-center py-2.5",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {isLoading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Регистрация…
              </>
            ) : (
              "Создать аккаунт"
            )}
          </button>
        </form>
      </div>

      <p className="text-center text-xs text-qa-muted mt-6">
        Уже есть аккаунт?{" "}
        <Link href="/login" className="text-primary hover:text-accent">
          Войти
        </Link>
      </p>
      <LegalFooter />
    </div>
  );
}

export default function SignupPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg flex items-center justify-center px-4">
      <div
        className="fixed inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(var(--color-primary) 1px, transparent 1px), linear-gradient(90deg, var(--color-primary) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />
      <Suspense
        fallback={
          <div className="w-full max-w-sm text-center text-sm text-qa-muted">
            Загрузка…
          </div>
        }
      >
        <SignupForm />
      </Suspense>
    </div>
  );
}
