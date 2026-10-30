"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "react-hot-toast";
import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { adminSecurityApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";

export default function AdminSecurityPage() {
  const [code, setCode] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const checkQ = useQuery({
    queryKey: ["admin-login-check"],
    queryFn: () => adminSecurityApi.loginCheck(),
    retry: false,
  });

  const auditQ = useQuery({
    queryKey: ["admin-security-audit", actor, action, fromDate, toDate],
    queryFn: () =>
      adminSecurityApi.securityAudit({
        actor: actor || undefined,
        action: action || undefined,
        from: fromDate || undefined,
        to: toDate || undefined,
      }),
    enabled: !!checkQ.data?.ok,
  });

  const setupMut = useMutation({
    mutationFn: () => adminSecurityApi.mfaSetup(),
    onSuccess: (d) => {
      setSecret(d.secret);
      toast.success("TOTP secret создан — добавьте в Authenticator");
    },
    onError: (e) => toast.error(extractErrorMessage(e, "MFA setup failed")),
  });

  const verifyMut = useMutation({
    mutationFn: () => adminSecurityApi.mfaVerify(code),
    onSuccess: () => {
      toast.success("Защита входа включена");
      checkQ.refetch();
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Код не подошёл")),
  });

  return (
    <OperatorDetailShell
      title="Admin Security"
      description="Отдельный admin-контур: MFA (TOTP), Security & Audit (owner_admin)."
    >
      <div className="space-y-4 max-w-3xl">
        <a href="/operator/admissions/accounts" className="text-xs text-terminal-accent hover:underline">
          Счета площадки — страница в разделе Допуски
        </a>
        {checkQ.isError && (
          <p className="text-sm text-terminal-down">Нет доступа к admin path для этой роли.</p>
        )}
        {checkQ.data && (
          <div className="cockpit-panel p-4 text-xs space-y-2">
            <div>Role: <span className="font-mono text-white">{checkQ.data.system_role}</span></div>
            <div>MFA: {checkQ.data.mfa_enabled ? "enabled" : "required / not enabled"}</div>
            <div className="flex flex-wrap gap-2 pt-2">
              <button type="button" className="btn-secondary text-xs" onClick={() => setupMut.mutate()}>
                Setup TOTP
              </button>
              <input
                className="input text-xs w-28"
                placeholder="6-digit"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <button
                type="button"
                className="btn-primary text-xs"
                disabled={code.length < 6}
                onClick={() => verifyMut.mutate()}
              >
                Verify MFA
              </button>
            </div>
            {secret && (
              <p className="text-[10px] text-terminal-accent break-all pt-2">Secret: {secret}</p>
            )}
          </div>
        )}

        <div className="cockpit-panel p-4">
          <h2 className="text-sm font-semibold mb-2">Security &amp; Audit</h2>
          <div className="flex flex-wrap gap-2 mb-3 text-[11px]">
            <input className="input text-xs w-32" placeholder="actor user_id" value={actor} onChange={(e) => setActor(e.target.value)} />
            <input className="input text-xs w-36" placeholder="action" value={action} onChange={(e) => setAction(e.target.value)} />
            <input className="input text-xs w-40" type="datetime-local" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
            <input className="input text-xs w-40" type="datetime-local" value={toDate} onChange={(e) => setToDate(e.target.value)} />
          </div>
          <div className="space-y-1 max-h-96 overflow-y-auto text-[11px]">
            {(auditQ.data?.items ?? []).length === 0 && (
              <p className="text-qa-muted">Пока нет security-событий.</p>
            )}
            {(auditQ.data?.items ?? []).map((row: any) => (
              <div key={row.id} className="border-b border-cockpit-border/50 py-1.5">
                <span className="text-qa-muted tabular-nums">{row.timestamp}</span>{" "}
                <span className="text-terminal-accent font-mono">{row.action}</span>{" "}
                <span className="text-qa-muted">{row.resource_type}/{row.resource_id}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </OperatorDetailShell>
  );
}
