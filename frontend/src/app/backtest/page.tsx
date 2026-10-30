import { redirect } from "next/navigation";

/** Backtest UI removed — redirect to dashboard. */
export default function BacktestPage() {
  redirect("/");
}
