import { redirect } from "next/navigation";

/** Legacy path — Fincept hub lives at /terminal. */
export default function FinceptRedirectPage() {
  redirect("/terminal");
}
