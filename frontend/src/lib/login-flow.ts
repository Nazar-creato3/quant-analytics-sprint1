/**
 * Multi-step login orchestration: password → change-password → WebAuthn register → WebAuthn assert → session.
 */
import { authApi, finalizeAuthenticatedSession } from "@/lib/api";
import {
  createPlatformCredential,
  getPlatformAssertion,
  isWebAuthnAvailable,
} from "@/lib/webauthn-client";
import { markTwoFactorEnrollmentRequired } from "@/lib/post-login-nav";
import type { TokenResponse } from "@/types";

export type LoginStep =
  | "credentials"
  | "change_password"
  | "webauthn_register"
  | "webauthn_assert"
  | "two_factor";

export type LoginAttemptResult =
  | { step: "authenticated"; tokens: TokenResponse }
  | { step: "change_password" }
  | { step: "webauthn_register" }
  | { step: "webauthn_assert" }
  | {
      step: "two_factor";
      pending_token: string;
      backup_allowed: boolean;
      enrollment_required?: boolean;
    };

function classifyLoginResponse(data: TokenResponse): LoginAttemptResult | Promise<LoginAttemptResult> {
  if (data.must_change_password) return { step: "change_password" };
  if (data.webauthn_registration_required) return { step: "webauthn_register" };
  if (data.webauthn_required) return { step: "webauthn_assert" };
  if (data.two_factor_required && data.two_factor_pending_token) {
    return {
      step: "two_factor",
      pending_token: data.two_factor_pending_token,
      backup_allowed: Boolean(data.two_factor_backup_allowed),
    };
  }
  if (!data.access_token) {
    throw new Error("Login failed: server returned no access token");
  }
  if (data.two_factor_enrollment_required) {
    markTwoFactorEnrollmentRequired();
  }
  return finalizeAuthenticatedSession(data).then(() => ({
    step: "authenticated" as const,
    tokens: data,
  }));
}

export async function verifyTwoFactorLogin(
  pendingToken: string,
  code?: string,
  backupCode?: string,
): Promise<LoginAttemptResult> {
  const data = await authApi.verifyTwoFactor({
    pending_token: pendingToken,
    code,
    backup_code: backupCode,
  });
  return await classifyLoginResponse(data);
}

export type LoginExtras = {
  fingerprint?: string;
  user_agent?: string;
};

/** First password login — does not persist partial/empty tokens. */
export async function attemptPasswordLogin(
  email: string,
  password: string,
  extras?: LoginExtras,
  webauthnCredential?: Record<string, unknown>,
): Promise<LoginAttemptResult> {
  const data = await authApi.loginRaw(email, password, {
    ...extras,
    webauthn_credential: webauthnCredential,
  });
  return await classifyLoginResponse(data);
}

export async function changePasswordAndContinue(
  email: string,
  currentPassword: string,
  newPassword: string,
): Promise<{ ok: boolean; webauthn_registration_required: boolean }> {
  return authApi.changePassword(email, currentPassword, newPassword);
}

export async function registerWebAuthnDevice(
  email: string,
  password: string,
): Promise<void> {
  if (!isWebAuthnAvailable()) {
    throw new Error("WebAuthn не поддерживается в этом браузере");
  }
  const options = await authApi.webauthnRegisterOptions(email, password);
  const credential = await createPlatformCredential(options);
  await authApi.webauthnRegisterVerify(email, password, credential);
}

export async function performWebAuthnAssertion(email: string): Promise<Record<string, unknown>> {
  if (!isWebAuthnAvailable()) {
    throw new Error("WebAuthn не поддерживается в этом браузере");
  }
  const options = await authApi.webauthnLoginOptions(email);
  return getPlatformAssertion(options);
}

/**
 * Run the full login pipeline until authenticated or a user-action step is required.
 * Returns the next step when user input is needed (change password, WebAuthn).
 */
export async function runLoginPipeline(
  email: string,
  password: string,
  extras?: LoginExtras,
  webauthnCredential?: Record<string, unknown>,
): Promise<LoginAttemptResult> {
  return attemptPasswordLogin(email, password, extras, webauthnCredential);
}
