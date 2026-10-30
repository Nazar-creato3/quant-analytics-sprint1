"use client";

import { useEffect, useState } from "react";
import { Phone } from "lucide-react";
import { authApi } from "@/lib/api";

/** Russian mobile, any common spelling → +7 9XX… or null. */
export function normalizeRuMobile(raw: string): string | null {
  let d = raw.replace(/\D/g, "");
  if (d.length === 11 && d.startsWith("8")) d = `7${d.slice(1)}`;
  if (d.length === 10 && d.startsWith("9")) d = `7${d}`;
  return /^79\d{9}$/.test(d) ? `+${d}` : null;
}

function apiError(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" && detail.trim() ? detail : fallback;
}

/**
 * Phone + SMS code. Reports the confirmed pair upward; the code itself is
 * checked on the server (sign-up or /auth/phone/confirm).
 */
export function PhoneCodeField({
  onChange,
  disabled,
}: {
  onChange: (value: { phone: string; code: string } | null) => void;
  disabled?: boolean;
}) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = window.setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => window.clearTimeout(t);
  }, [cooldown]);

  useEffect(() => {
    const normalized = normalizeRuMobile(phone);
    onChange(normalized && sentTo === normalized && /^\d{6}$/.test(code) ? { phone: normalized, code } : null);
  }, [phone, code, sentTo, onChange]);

  const send = async () => {
    setError(null);
    const normalized = normalizeRuMobile(phone);
    if (!normalized) {
      setError("Укажите российский мобильный номер: +7 9XX XXX-XX-XX");
      return;
    }
    setBusy(true);
    try {
      const out = await authApi.sendPhoneCode(normalized);
      setSentTo(normalized);
      setCooldown(60);
      if (out.dev_code) setCode(out.dev_code);
    } catch (e) {
      setError(apiError(e, "Не удалось отправить код. Попробуйте позже."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2" data-testid="phone-code-field">
      <label className="label" htmlFor="phone-input">
        Мобильный телефон
      </label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Phone size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
          <input
            id="phone-input"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            className="input pl-9"
            placeholder="+7 900 000-00-00"
            value={phone}
            disabled={disabled}
            onChange={(e) => setPhone(e.target.value)}
          />
        </div>
        <button
          type="button"
          className="btn-ghost text-xs whitespace-nowrap"
          onClick={send}
          disabled={disabled || busy || cooldown > 0}
          data-testid="phone-send"
        >
          {cooldown > 0 ? `Повторно через ${cooldown} с` : sentTo ? "Отправить ещё раз" : "Получить код"}
        </button>
      </div>
      {sentTo && (
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          className="input tracking-[0.4em] text-center"
          placeholder="Код из СМС"
          value={code}
          disabled={disabled}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          data-testid="phone-code"
        />
      )}
      {error && <p className="text-xs text-terminal-down">{error}</p>}
    </div>
  );
}
