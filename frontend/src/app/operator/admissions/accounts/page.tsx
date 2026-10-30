"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { AdmissionsSubnav } from "@/components/operator/AdmissionsSubnav";
import { FleetAuditPanel } from "@/components/operator/FleetAuditPanel";
import { useAuth } from "@/hooks";

export default function AdmissionsAccountsPage() {
  const router = useRouter();
  const { isAdmin, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading && !isAdmin) {
      router.replace("/operator/admissions");
    }
  }, [isAdmin, isLoading, router]);

  if (isLoading || !isAdmin) {
    return null;
  }

  return (
    <OperatorDetailShell
      title="Допуски"
      description="Счета площадки — внутренняя книга пользователей. Не идёт в анализ рынка и не дергает брокеров."
      fillViewport
    >
      <div className="flex flex-col flex-1 min-h-0 gap-4 overflow-hidden">
        <AdmissionsSubnav />
        <div className="flex-1 min-h-0 overflow-y-auto">
          <FleetAuditPanel />
        </div>
      </div>
    </OperatorDetailShell>
  );
}
