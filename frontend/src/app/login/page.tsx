"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { ThemeLogo } from "@/components/shared/ThemeLogo";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { devicesApi } from "@/lib/api";
import { getBrowserFingerprint } from "@/lib/device-fingerprint";
import {
  attemptPasswordLogin,
  changePasswordAndContinue,
  performWebAuthnAssertion,
  registerWebAuthnDevice,
  verifyTwoFactorLogin,
  type LoginStep,
} from "@/lib/login-flow";
import {
  clearLegacyCredentialStorage,
  stripSensitiveLoginQueryParams,
  urlHasSensitiveLoginQueryParams,
} from "@/lib/login-security";
import { navigateAfterLogin } from "@/lib/post-login-nav";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { clsx } from "clsx";
import { Eye, EyeOff, Lock, Mail, AlertCircle, Shield, KeyRound } from "lucide-react";
import { toast } from "react-hot-toast";

const STEP_HINTS: Record<LoginStep, string> = {
  credentials: "Вход в платформу Quant Analytics",
  change_password: "Смените временный пароль для продолжения",
  webauthn_register: "Привяжите это устройство для безопасного входа",
  webauthn_assert: "Подтвердите вход на этом устройстве",
  two_factor: "Введите код из приложения двухфакторной защиты",
};

function LoginForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<LoginStep>("credentials");
  const [fieldsLocked, setFieldsLocked] = useState(true);
  const [pending2faToken, setPending2faToken] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [useBackup, setUseBackup] = useState(false);
  const [backupCode, setBackupCode] = useState("");

  useEffect(() => {
    clearLegacyCredentialStorage();

    if (typeof window !== "undefined" && urlHasSensitiveLoginQueryParams(window.location.href)) {
      const safe = stripSensitiveLoginQueryParams(new URL(window.location.href));
      window.history.replaceState(null, "", `${safe.pathname}${safe.search}${safe.hash}`);
    }

    const unlock = window.setTimeout(() => setFieldsLocked(false), 100);
    return () => window.clearTimeout(unlock);
  }, []);

  const redirectAfterLogin = useCallback(async () => {
    try {
      const fingerprint = await getBrowserFingerprint();
      await devicesApi.bind(fingerprint, navigator.userAgent);
    } catch {
      /* device bind best-effort */
    }
    navigateAfterLogin(searchParams.get("from"));
  }, [searchParams]);

  const runAuthPipeline = useCallback(
    async (pwd: string, webauthnCredential?: Record<string, unknown>) => {
      const fingerprint = await getBrowserFingerprint();
      const extras = { fingerprint, user_agent: navigator.userAgent };

      let result = await attemptPasswordLogin(email.trim(), pwd, extras, webauthnCredential);

      while (result.step !== "authenticated") {
        if (result.step === "change_password") {
          setStep("change_password");
          return;
        }
        if (result.step === "webauthn_register") {
          setStep("webauthn_register");
          setIsLoading(true);
          await registerWebAuthnDevice(email.trim(), pwd);
          result = await attemptPasswordLogin(email.trim(), pwd, extras);
          continue;
        }
        if (result.step === "webauthn_assert") {
          setStep("webauthn_assert");
          setIsLoading(true);
          const credential = await performWebAuthnAssertion(email.trim());
          result = await attemptPasswordLogin(email.trim(), pwd, extras, credential);
          continue;
        }
        if (result.step === "two_factor") {
          setPending2faToken(result.pending_token);
          setStep("two_factor");
          return;
        }
        throw new Error("Unknown login step");
      }

      await redirectAfterLogin();
    },
    [email, redirectAfterLogin],
  );

  const handleTwoFactorSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pending2faToken) return;
    setError(null);
    setIsLoading(true);
    try {
      const result = await verifyTwoFactorLogin(
        pending2faToken,
        useBackup ? undefined : totpCode,
        useBackup ? backupCode : undefined,
      );
      if (result.step !== "authenticated") {
        throw new Error("2FA incomplete");
      }
      toast.success("Вход выполнен");
      setPending2faToken(null);
      await redirectAfterLogin();
    } catch (err: unknown) {
      setError(formatLoginError(err));
      toast.error(formatLoginError(err));
    } finally {
      setIsLoading(false);
    }
  };

  const handleCredentialsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await runAuthPipeline(password);
    } catch (err: unknown) {
      setError(formatLoginError(err));
      setStep("credentials");
    } finally {
      setIsLoading(false);
    }
  };

  const handleChangePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (newPassword.length < 8) {
      setError("Новый пароль должен быть не короче 8 символов");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Пароли не совпадают");
      return;
    }
    setIsLoading(true);
    try {
      const { webauthn_registration_required } = await changePasswordAndContinue(
        email.trim(),
        password,
        newPassword,
      );
      setPassword(newPassword);
      setNewPassword("");
      setConfirmPassword("");
      if (webauthn_registration_required) {
        setStep("webauthn_register");
        await registerWebAuthnDevice(email.trim(), newPassword);
      }
      await runAuthPipeline(newPassword);
    } catch (err: unknown) {
      setError(formatLoginError(err));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full max-w-sm relative">
      <div className="text-center mb-8">
        <div className="mb-4">
          <ThemeLogo width={72} height={72} priority className="mx-auto" />
        </div>
        <h1 className="text-2xl font-bold text-qa-text tracking-tight">Quant Analytics</h1>
        <p className="text-sm text-qa-muted mt-1">{STEP_HINTS[step]}</p>
      </div>

      <div className="card p-6">
        {step === "credentials" && (
          <form onSubmit={handleCredentialsSubmit} className="space-y-4" autoComplete="off">
            <EmailField
              email={email}
              setEmail={setEmail}
              fieldsLocked={fieldsLocked}
              setFieldsLocked={setFieldsLocked}
            />
            <PasswordField
              label="Пароль"
              id="login-password"
              value={password}
              onChange={setPassword}
              showPassword={showPassword}
              setShowPassword={setShowPassword}
              fieldsLocked={fieldsLocked}
              setFieldsLocked={setFieldsLocked}
            />
            {error && <ErrorBanner message={error} />}
            <div className="flex justify-end">
              <Link href="/recover" className="text-xs text-primary hover:text-accent">
                Забыли пароль?
              </Link>
            </div>
            <SubmitButton isLoading={isLoading} disabled={!email || !password} label="Войти" />
          </form>
        )}

        {step === "change_password" && (
          <form onSubmit={handleChangePasswordSubmit} className="space-y-4" autoComplete="off">
            <div className="flex items-center gap-2 text-sm text-qa-muted mb-2">
              <KeyRound size={14} />
              <span>Аккаунт {email}</span>
            </div>
            <PasswordField
              label="Новый пароль"
              id="new-password"
              value={newPassword}
              onChange={setNewPassword}
              showPassword={showPassword}
              setShowPassword={setShowPassword}
              fieldsLocked={false}
              setFieldsLocked={setFieldsLocked}
            />
            <PasswordField
              label="Подтвердите пароль"
              id="confirm-password"
              value={confirmPassword}
              onChange={setConfirmPassword}
              showPassword={showPassword}
              setShowPassword={setShowPassword}
              fieldsLocked={false}
              setFieldsLocked={setFieldsLocked}
            />
            {error && <ErrorBanner message={error} />}
            <SubmitButton
              isLoading={isLoading}
              disabled={!newPassword || !confirmPassword}
              label="Сменить пароль и продолжить"
            />
          </form>
        )}

        {step === "two_factor" && (
          <form onSubmit={handleTwoFactorSubmit} className="space-y-4">
            <div className="text-center">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 text-primary mb-2">
                <KeyRound size={22} />
              </div>
              <p className="text-sm text-qa-muted">
                Код из приложения двухфакторной защиты
              </p>
            </div>
            {!useBackup ? (
              <input
                inputMode="numeric"
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                className="w-full px-3 py-3 rounded border border-cockpit-border bg-cockpit-bg text-center text-2xl tracking-[0.4em] tabular-nums"
                placeholder="000000"
                autoFocus
              />
            ) : (
              <input
                value={backupCode}
                onChange={(e) => setBackupCode(e.target.value.toUpperCase())}
                className="w-full px-3 py-2 rounded border border-cockpit-border bg-cockpit-bg text-center font-mono"
                placeholder="РЕЗЕРВНЫЙ КОД"
                autoFocus
              />
            )}
            {error && <ErrorBanner message={error} />}
            <SubmitButton
              isLoading={isLoading}
              disabled={useBackup ? backupCode.length < 8 : totpCode.length !== 6}
              label="Подтвердить"
            />
            <button
              type="button"
              className="w-full text-xs text-primary"
              onClick={() => setUseBackup((v) => !v)}
            >
              {useBackup ? "Использовать код из приложения" : "Использовать резервный код"}
            </button>
            <button
              type="button"
              className="w-full text-xs text-qa-muted"
              onClick={() => {
                setStep("credentials");
                setPending2faToken(null);
                setTotpCode("");
                setBackupCode("");
              }}
            >
              Назад
            </button>
          </form>
        )}

        {(step === "webauthn_register" || step === "webauthn_assert") && (
          <div className="space-y-4 text-center py-4">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 text-primary">
              <Shield size={22} />
            </div>
            <p className="text-sm text-qa-muted">
              {step === "webauthn_register"
                ? "Следуйте подсказкам браузера для привязки устройства…"
                : "Подтвердите личность через системную проверку…"}
            </p>
            {isLoading && (
              <span className="inline-flex w-3.5 h-3.5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
            )}
            {error && <ErrorBanner message={error} />}
          </div>
        )}
      </div>

      <p className="text-center text-xs text-qa-muted mt-6">
        Нет доступа?{" "}
        <Link href="/apply" className="text-primary hover:text-accent">
          Зарегистрироваться
        </Link>
      </p>
      <LegalFooter />
    </div>
  );
}

function EmailField({
  email,
  setEmail,
  fieldsLocked,
  setFieldsLocked,
}: {
  email: string;
  setEmail: (v: string) => void;
  fieldsLocked: boolean;
  setFieldsLocked: (v: boolean) => void;
}) {
  return (
    <div>
      <label className="label" htmlFor="login-email">
        Почта
      </label>
      <div className="relative">
        <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
        <input
          id="login-email"
          name="login-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onFocus={() => setFieldsLocked(false)}
          readOnly={fieldsLocked}
          placeholder="you@example.com"
          required
          autoComplete="off"
          data-1p-ignore
          data-lpignore="true"
          className="input pl-9"
        />
      </div>
    </div>
  );
}

function PasswordField({
  label,
  id,
  value,
  onChange,
  showPassword,
  setShowPassword,
  fieldsLocked,
  setFieldsLocked,
}: {
  label: string;
  id: string;
  value: string;
  onChange: (v: string) => void;
  showPassword: boolean;
  setShowPassword: (v: boolean) => void;
  fieldsLocked: boolean;
  setFieldsLocked: (v: boolean) => void;
}) {
  return (
    <div>
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <div className="relative">
        <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
        <input
          id={id}
          name={id}
          type={showPassword ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFieldsLocked(false)}
          readOnly={fieldsLocked}
          placeholder="••••••••"
          required
          autoComplete="new-password"
          data-1p-ignore
          data-lpignore="true"
          className="input pl-9 pr-9"
        />
        <button
          type="button"
          aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
          onClick={() => setShowPassword(!showPassword)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-qa-muted hover:text-qa-text transition-colors"
        >
          {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="alert-error">
      <AlertCircle size={13} className="shrink-0 mt-0.5" />
      <span>{message}</span>
    </div>
  );
}

function SubmitButton({
  isLoading,
  disabled,
  label,
}: {
  isLoading: boolean;
  disabled: boolean;
  label: string;
}) {
  return (
    <button
      type="submit"
      disabled={isLoading || disabled}
      className={clsx(
        "btn-primary w-full justify-center py-2.5",
        "disabled:opacity-50 disabled:cursor-not-allowed",
      )}
    >
      {isLoading ? (
        <>
          <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          Вход…
        </>
      ) : (
        label
      )}
    </button>
  );
}

function formatLoginError(err: unknown): string {
  const anyErr = err as {
    response?: { status?: number; data?: { detail?: string }; headers?: Record<string, string> };
    message?: string;
    name?: string;
  };
  const status = anyErr?.response?.status;
  const headers = anyErr?.response?.headers ?? {};
  const retryAfterRaw = headers["retry-after"] ?? headers["Retry-After"];
  const retryAfterSec = retryAfterRaw ? Number.parseInt(String(retryAfterRaw), 10) : NaN;

  const raw = anyErr?.response?.data?.detail || anyErr?.message || "Ошибка входа";
  const msg =
    raw === "Network Error"
      ? "Не удалось связаться с сервером. Проверьте соединение или обратитесь к admin."
      : raw;
  if (status === 429) {
    if (Number.isFinite(retryAfterSec) && retryAfterSec > 0) {
      const minutes = Math.max(1, Math.ceil(retryAfterSec / 60));
      return `Слишком много попыток входа. Повторите через ${minutes} мин.`;
    }
    if (msg.includes("неудачных попыток") || msg.includes("Слишком много")) return msg;
    return "Слишком много попыток входа. Повторите через несколько минут.";
  }
  if (msg === "Invalid email or password") return "Неверный email или пароль";
  if (msg === "Not whitelisted" || msg.includes("Нет доступа к платформе")) {
    return "Нет доступа к платформе. Обратитесь к администратору.";
  }
  if (msg.includes("ещё не одобрена")) {
    return "Вы на пробном периоде. Полный доступ откроет администратор.";
  }
  if (msg === "WebAuthn registration cancelled" || msg === "WebAuthn verification cancelled") {
    return "Проверка устройства отменена. Повторите вход.";
  }
  if (msg === "WebAuthn verification timed out") {
    return "Проверка устройства заняла слишком много времени. Повторите вход с уже привязанного устройства.";
  }
  if (
    anyErr?.name === "NotAllowedError" ||
    anyErr?.name === "SecurityError" ||
    anyErr?.message?.includes("webauthn-2/#sctn-privacy-considerations-client") ||
    msg.includes("webauthn-2/#sctn-privacy-considerations-client") ||
    msg.includes("timed out or was not allowed") ||
    msg.includes("The operation either timed out or was not allowed")
  ) {
    return "Браузер не нашёл привязанный ключ. Войдите с ранее привязанного устройства или попросите администратора сбросить привязку.";
  }
  if (msg === "WebAuthn не поддерживается в этом браузере") return msg;
  return String(msg);
}

export default function LoginPage() {
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
        <LoginForm />
      </Suspense>
    </div>
  );
}
