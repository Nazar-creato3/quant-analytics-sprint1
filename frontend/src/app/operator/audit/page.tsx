import { redirect } from "next/navigation";

/** Operator audit UI removed — redirect to dashboard. */
export default function OperatorAuditPage() {
  redirect("/");
}
