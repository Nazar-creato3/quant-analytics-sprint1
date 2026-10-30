"use client";

import { useState } from "react";
import Link from "next/link";
import { ThemeLogo } from "@/components/shared/ThemeLogo";
import { authApi } from "@/lib/api";
import { RegistrationConsents, consentsGiven } from "@/components/auth/RegistrationConsents";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { markOnboardingOffer } from "@/lib/onboarding/storage";
import { clsx } from "clsx";
import { AlertCircle, Eye, EyeOff, Lock, Mail, Phone, User } from "lucide-react";

export default function ApplyPage() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [phone, setPhone] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [capitalRange, setCapitalRange] = useState("");
  const [experience, setExperience] = useState("");
  const [strategy, setStrategy] = useState("");
  const [comments, setComments] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consents, setConsents] = useState({ acceptTerms: false, consentPd: false });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Пароль должен быть не короче 8 символов");
      return;
    }
    setIsLoading(true);
    try {
      await authApi.register({
        email: email.trim(),
        password,
        accept_terms: consents.acceptTerms,
        consent_pd: consents.consentPd,
        contact_name: name.trim() || undefined,
        contact_phone: phone.trim() || undefined,
        jurisdiction: jurisdiction || undefined,
        capital_range: capitalRange || undefined,
        experience_level: experience || undefined,
        strategy_interest: strategy.trim() || undefined,
        notes: comments.trim() || undefined,
      });
      markOnboardingOffer();
      window.location.href = "/";
    } catch (err: any) {
      const raw = err?.response?.data?.detail || err?.message || "";
      const msg = typeof raw === "string" ? raw : "";
      setError(
        msg === "Email already registered"
          ? "Этот адрес уже зарегистрирован. Войдите."
          : "Не удалось отправить заявку.",
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-qa-bg flex flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-lg relative">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center mb-4">
            <ThemeLogo width={56} height={56} priority />
          </div>
          <h1 className="text-2xl font-bold text-qa-text tracking-tight">Регистрация</h1>
          <p className="text-sm text-qa-muted mt-1">
            Сразу откроется демо: графики, прогнозы и бумажная торговля. Live — после одобрения и ваших API-ключей.
          </p>
        </div>

        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="label" htmlFor="apply-name">Имя</label>
                <div className="relative">
                  <User size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
                  <input id="apply-name" value={name} onChange={(e) => setName(e.target.value)} className="input pl-9" placeholder="Имя" />
                </div>
              </div>
              <div>
                <label className="label" htmlFor="apply-email">Email *</label>
                <div className="relative">
                  <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
                  <input id="apply-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="input pl-9" placeholder="you@example.com" />
                </div>
              </div>
            </div>

            <div>
              <label className="label" htmlFor="apply-password">Пароль *</label>
              <div className="relative">
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
                <input
                  id="apply-password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="input pl-9 pr-10"
                  placeholder="минимум 8 символов"
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-qa-muted"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
                >
                  {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <div>
              <label className="label" htmlFor="apply-phone">Телефон</label>
              <div className="relative">
                <Phone size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-qa-muted" />
                <input id="apply-phone" value={phone} onChange={(e) => setPhone(e.target.value)} className="input pl-9" placeholder="+7 …" />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="label" htmlFor="apply-jurisdiction">Юрисдикция</label>
                <select id="apply-jurisdiction" value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} className="input">
                  <option value="">—</option>
                  <option value="RU">Россия</option>
                  <option value="EU">ЕС</option>
                  <option value="US">США</option>
                  <option value="OTHER">Другое</option>
                </select>
              </div>
              <div>
                <label className="label" htmlFor="apply-capital">Капитал</label>
                <select id="apply-capital" value={capitalRange} onChange={(e) => setCapitalRange(e.target.value)} className="input">
                  <option value="">—</option>
                  <option value="under_50k">&lt; $50k</option>
                  <option value="50k_250k">$50k–250k</option>
                  <option value="250k_1m">$250k–1M</option>
                  <option value="over_1m">&gt; $1M</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="label" htmlFor="apply-exp">Опыт</label>
                <select id="apply-exp" value={experience} onChange={(e) => setExperience(e.target.value)} className="input">
                  <option value="">—</option>
                  <option value="beginner">Начинающий</option>
                  <option value="intermediate">Средний</option>
                  <option value="advanced">Продвинутый</option>
                  <option value="professional">Профессионал</option>
                </select>
              </div>
              <div>
                <label className="label" htmlFor="apply-strategy">Интерес к стратегиям</label>
                <input id="apply-strategy" value={strategy} onChange={(e) => setStrategy(e.target.value)} className="input" placeholder="momentum, grid, macro…" />
              </div>
            </div>

            <div>
              <label className="label" htmlFor="apply-notes">Комментарий</label>
              <textarea id="apply-notes" value={comments} onChange={(e) => setComments(e.target.value)} className="input min-h-[80px]" placeholder="Кратко о целях и опыте" />
            </div>

            <RegistrationConsents value={consents} onChange={setConsents} />

            {error && (
              <div className="alert-error">
                <AlertCircle size={13} className="shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading || !email || password.length < 8 || !consentsGiven(consents)}
              className={clsx("btn-primary w-full justify-center py-2.5", "disabled:opacity-50 disabled:cursor-not-allowed")}
            >
              {isLoading ? "Отправка…" : "Зарегистрироваться"}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-qa-muted mt-6">
          Уже есть доступ?{" "}
          <Link href="/login" className="text-terminal-accent hover:text-terminal-accent">
            Войти
          </Link>
        </p>
        <LegalFooter />
      </div>
    </div>
  );
}
