/** Browser WebAuthn helpers — converts backend JSON options to Credential API calls. */

const CLIENT_WEBAUTHN_TIMEOUT_MS = 15000;

function webauthnTimeout(options: Record<string, unknown>): number {
  const serverTimeout = Number(options.timeout);
  if (!Number.isFinite(serverTimeout) || serverTimeout <= 0) return CLIENT_WEBAUTHN_TIMEOUT_MS;
  return Math.min(serverTimeout, CLIENT_WEBAUTHN_TIMEOUT_MS);
}

async function withAbortableCredential<T>(
  timeoutMs: number,
  fn: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs + 1000);
  try {
    return await fn(controller.signal);
  } catch (err) {
    const domErr = err as { name?: string; message?: string };
    if (domErr?.name === "AbortError") {
      throw new Error("WebAuthn verification timed out");
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

function base64UrlToBuffer(base64url: string): ArrayBuffer {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const base64 = (base64url + pad).replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function bufferToBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function credentialIdToBuffer(id: string): ArrayBuffer {
  try {
    return base64UrlToBuffer(id);
  } catch {
    return new TextEncoder().encode(id).buffer;
  }
}

export function isWebAuthnAvailable(): boolean {
  return typeof window !== "undefined" && !!window.PublicKeyCredential;
}

export async function createPlatformCredential(
  options: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const user = options.user as { id: string; name: string; displayName: string };
  const timeout = webauthnTimeout(options);
  const cred = await withAbortableCredential(timeout, (signal) =>
    navigator.credentials.create({
      signal,
      publicKey: {
        challenge: base64UrlToBuffer(String(options.challenge)),
        rp: options.rp as PublicKeyCredentialRpEntity,
        user: {
          id: base64UrlToBuffer(user.id),
          name: user.name,
          displayName: user.displayName,
        },
        pubKeyCredParams: options.pubKeyCredParams as PublicKeyCredentialParameters[],
        authenticatorSelection: options.authenticatorSelection as AuthenticatorSelectionCriteria,
        timeout,
        attestation: (options.attestation as AttestationConveyancePreference) ?? "none",
      },
    }) as Promise<Credential | null>,
  ) as PublicKeyCredential | null;

  if (!cred) throw new Error("WebAuthn registration cancelled");

  const response = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id,
    rawId: bufferToBase64Url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufferToBase64Url(response.clientDataJSON),
      attestationObject: bufferToBase64Url(response.attestationObject),
    },
  };
}

export async function getPlatformAssertion(
  options: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const allowCredentials = (
    (options.allowCredentials as Array<{ type: string; id: string }>) ?? []
  ).map((c) => ({
    type: c.type as PublicKeyCredentialType,
    id: credentialIdToBuffer(c.id),
  }));

  const timeout = webauthnTimeout(options);
  const cred = await withAbortableCredential(timeout, (signal) =>
    navigator.credentials.get({
      signal,
      publicKey: {
        challenge: base64UrlToBuffer(String(options.challenge)),
        timeout,
        rpId: options.rpId as string,
        allowCredentials,
        userVerification: (options.userVerification as UserVerificationRequirement) ?? "required",
      },
    }) as Promise<Credential | null>,
  ) as PublicKeyCredential | null;

  if (!cred) throw new Error("WebAuthn verification cancelled");

  const response = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: bufferToBase64Url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufferToBase64Url(response.clientDataJSON),
      authenticatorData: bufferToBase64Url(response.authenticatorData),
      signature: bufferToBase64Url(response.signature),
    },
  };
}
