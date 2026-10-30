"use client";

import Link from "next/link";

export type RegistrationConsentState = { acceptTerms: boolean; consentPd: boolean };

/**
 * Two separate ticks, both off by default (152-ФЗ, ст. 9: согласие — отдельное,
 * конкретное и информированное). The server stores each one with the text
 * version and time; without both the account is not created.
 */
export function RegistrationConsents({
  value,
  onChange,
}: {
  value: RegistrationConsentState;
  onChange: (next: RegistrationConsentState) => void;
}) {
  return (
    <fieldset className="space-y-2 text-xs text-qa-muted" data-testid="registration-consents">
      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={value.acceptTerms}
          onChange={(e) => onChange({ ...value, acceptTerms: e.target.checked })}
          data-testid="consent-terms"
        />
        <span>
          Мне исполнилось 18 лет. Принимаю{" "}
          <Link href="/legal/terms" target="_blank" className="text-primary hover:underline">
            пользовательское соглашение
          </Link>
        </span>
      </label>
      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={value.consentPd}
          onChange={(e) => onChange({ ...value, consentPd: e.target.checked })}
          data-testid="consent-pd"
        />
        <span>
          Даю{" "}
          <Link href="/legal/consent_pd" target="_blank" className="text-primary hover:underline">
            согласие на обработку персональных данных
          </Link>{" "}
          в соответствии с{" "}
          <Link href="/legal/privacy" target="_blank" className="text-primary hover:underline">
            политикой обработки
          </Link>
        </span>
      </label>
    </fieldset>
  );
}

export const consentsGiven = (v: RegistrationConsentState) => v.acceptTerms && v.consentPd;
