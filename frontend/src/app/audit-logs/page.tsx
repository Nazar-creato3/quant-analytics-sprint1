import { redirect } from "next/navigation";

/** Audit log UI removed — redirect to dashboard. */
export default function AuditLogsPage() {
  redirect("/");
}
