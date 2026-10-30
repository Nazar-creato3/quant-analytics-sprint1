import { twoFactorApi } from "@/lib/api";

/** If 2FA is enabled, exchange a TOTP code for a one-shot reauth_token. */
export async function resolveReauthToken(
  twoFactorEnabled: boolean,
  totpCode: string,
): Promise<string | undefined> {
  if (!twoFactorEnabled) return undefined;
  const code = totpCode.replace(/\D/g, "").slice(0, 6);
  if (code.length !== 6) {
    throw new Error("Введите 6-значный код 2FA");
  }
  const res = await twoFactorApi.reauth(code);
  return res.reauth_token;
}
