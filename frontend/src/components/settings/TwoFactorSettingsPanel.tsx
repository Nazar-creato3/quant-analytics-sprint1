"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { twoFactorApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { toast } from "react-hot-toast";
import { clsx } from "clsx";
import { Shield, ShieldCheck, ShieldOff, Copy, Download } from "lucide-react";

export function TwoFactorSettingsPanel() {
  const qc = useQueryClient();
  const { data: status, isLoading } = useQuery({
    queryKey: ["two-factor-status"],
    queryFn: twoFactorApi.status,
  });

  const [secret, setSecret] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [uri, setUri] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [disablePwd, setDisablePwd] = useState("");
  const [disableCode, setDisableCode] = useState("");

  const initiate = useMutation({
    mutationFn: twoFactorApi.enableInitiate,
    onSuccess: (data) => {
      setSecret(data.secret);
      setQr(data.qr_code_base64 || null);
      setUri(data.provisioning_uri);
      toast.success("Отсканируйте QR в Google Authenticator / Authy");
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось начать настройку 2FA")),
  });

  const confirm = useMutation({
    mutationFn: () => twoFactorApi.enableConfirm(code),
    onSuccess: (data) => {
      setBackupCodes(data.backup_codes);
      setSecret(null);
      setQr(null);
      setUri(null);
      setCode("");
      qc.invalidateQueries({ queryKey: ["two-factor-status"] });
      toast.success("2FA включена — сохраните резервные коды");
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Неверный код")),
  });

  const disable = useMutation({
    mutationFn: () => twoFactorApi.disable(disableCode, disablePwd),
    onSuccess: () => {
      setDisableCode("");
      setDisablePwd("");
      qc.invalidateQueries({ queryKey: ["two-factor-status"] });
      toast.success("2FA отключена");
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось отключить 2FA")),
  });

  const regen = useMutation({
    mutationFn: () => twoFactorApi.regenerateBackupCodes(code),
    onSuccess: (data) => {
      setBackupCodes(data.backup_codes);
      setCode("");
      qc.invalidateQueries({ queryKey: ["two-factor-status"] });
      toast.success("Резервные коды обновлены");
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось обновить коды")),
  });

  if (isLoading) {
    return <p className="text-sm text-qa-muted">Загрузка статуса 2FA…</p>;
  }

  const enabled = Boolean(status?.enabled);
  const adminRequired = Boolean(status?.required_for_admin);

  return (
    <div className="cockpit-panel p-4 space-y-4" data-testid="two-factor-settings">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-qa-muted flex items-center gap-2">
            {enabled ? <ShieldCheck size={14} className="text-emerald-400" /> : <Shield size={14} />}
            Двухфакторная аутентификация (Google Authenticator)
          </h2>
          <p className="text-xs text-qa-muted mt-1 leading-relaxed">
            TOTP-код из приложения при каждом входе. Админам — обязательно.
          </p>
        </div>
        <span
          className={clsx(
            "shrink-0 px-2 py-0.5 rounded text-[10px] uppercase tracking-wide font-semibold",
            enabled ? "bg-emerald-500/15 text-emerald-300" : "bg-qa-muted/20 text-qa-muted",
          )}
        >
          {enabled ? "Включена" : "Выключена"}
        </span>
      </div>

      {adminRequired && !enabled ? (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          Для администратора 2FA обязательна. Включите сейчас — иначе критические действия будут
          ограничены.
        </div>
      ) : null}

      {!enabled && !secret ? (
        <button
          type="button"
          onClick={() => initiate.mutate()}
          disabled={initiate.isPending}
          className="w-full sm:w-auto px-4 py-2 rounded bg-terminal-accent text-black text-sm font-semibold disabled:opacity-50"
        >
          {initiate.isPending ? "…" : "Включить 2FA"}
        </button>
      ) : null}

      {secret ? (
        <div className="space-y-3">
          <p className="text-xs text-qa-text/90">1. Отсканируйте QR или введите секрет вручную:</p>
          {qr ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={qr} alt="2FA QR" className="mx-auto w-48 h-48 bg-white rounded p-2" />
          ) : uri ? (
            <p className="text-[10px] break-all text-qa-muted font-mono">{uri}</p>
          ) : null}
          <code className="block text-center text-sm tracking-wider bg-cockpit-bg px-3 py-2 rounded border border-cockpit-border">
            {secret}
          </code>
          <label className="block text-xs text-qa-muted">2. Код из приложения</label>
          <input
            inputMode="numeric"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            className="w-full px-3 py-2 rounded border border-cockpit-border bg-cockpit-bg text-center text-2xl tracking-[0.4em] tabular-nums"
            placeholder="000000"
          />
          <button
            type="button"
            disabled={confirm.isPending || code.length !== 6}
            onClick={() => confirm.mutate()}
            className="w-full px-4 py-2 rounded bg-emerald-600 text-white text-sm font-semibold disabled:opacity-50"
          >
            Подтвердить и включить
          </button>
        </div>
      ) : null}

      {backupCodes ? (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
          <p className="text-xs font-semibold text-amber-100">
            Сохраните резервные коды — больше не покажем
          </p>
          <pre className="text-xs font-mono bg-cockpit-bg/80 p-2 rounded overflow-x-auto">
            {backupCodes.join("\n")}
          </pre>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded border border-cockpit-border"
              onClick={() => {
                void navigator.clipboard.writeText(backupCodes.join("\n"));
                toast.success("Скопировано");
              }}
            >
              <Copy size={12} /> Копировать
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded border border-cockpit-border"
              onClick={() => {
                const blob = new Blob(
                  [`Quant Analytics backup codes\n${new Date().toISOString()}\n\n${backupCodes.join("\n")}`],
                  { type: "text/plain" },
                );
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "qa-2fa-backup-codes.txt";
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              <Download size={12} /> Скачать
            </button>
            <button
              type="button"
              className="text-[10px] text-qa-muted underline ml-auto"
              onClick={() => setBackupCodes(null)}
            >
              Я сохранил коды
            </button>
          </div>
        </div>
      ) : null}

      {enabled ? (
        <div className="space-y-4 border-t border-cockpit-border pt-4">
          <p className="text-[10px] text-qa-muted">
            Резервных кодов осталось: {status?.backup_codes_remaining ?? "—"}
          </p>
          <div className="space-y-2">
            <label className="text-xs text-qa-muted">Перевыпустить резервные коды (нужен TOTP)</label>
            <input
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              className="w-full px-3 py-2 rounded border border-cockpit-border bg-cockpit-bg text-center tracking-[0.3em]"
              placeholder="000000"
            />
            <button
              type="button"
              disabled={regen.isPending || code.length !== 6}
              onClick={() => regen.mutate()}
              className="px-3 py-1.5 text-xs rounded border border-sky-500/40 text-sky-300 disabled:opacity-50"
            >
              Новые резервные коды
            </button>
          </div>

          {!adminRequired ? (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold text-red-300 flex items-center gap-1">
                <ShieldOff size={12} /> Отключить 2FA
              </h3>
              <input
                inputMode="numeric"
                maxLength={6}
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                className="w-full px-3 py-2 rounded border border-cockpit-border bg-cockpit-bg text-center"
                placeholder="код 2FA"
              />
              <input
                type="password"
                value={disablePwd}
                onChange={(e) => setDisablePwd(e.target.value)}
                className="w-full px-3 py-2 rounded border border-cockpit-border bg-cockpit-bg"
                placeholder="пароль аккаунта"
              />
              <button
                type="button"
                disabled={disable.isPending}
                onClick={() => disable.mutate()}
                className="px-3 py-1.5 text-xs rounded bg-red-700/80 text-white disabled:opacity-50"
              >
                Отключить
              </button>
            </div>
          ) : (
            <p className="text-[10px] text-qa-muted">Администратор не может отключить 2FA из UI.</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
