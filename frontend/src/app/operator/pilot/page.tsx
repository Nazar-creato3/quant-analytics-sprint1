import { redirect } from "next/navigation";

/** Pilot Ops UI removed — redirect to dashboard. */
export default function OperatorPilotPage() {
  redirect("/");
}
