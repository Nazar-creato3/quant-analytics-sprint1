from pathlib import Path

ROOT = Path("/home/user1/myapp/frontend/src")

api = ROOT / "lib/api.ts"
text = api.read_text(encoding="utf-8")
if "tradingAccountsApi" not in text:
    block = """

export type TradingAccountOut = {
  id: string;
  venue: string;
  account_mode: "paper" | "live";
  status: string;
  label?: string | null;
  account_display?: string | null;
  connected: boolean;
  rotation_due_at: string;
};

export type ConnectRawKeyVenue = "binance" | "alpaca" | "tinkoff" | "tbank" | "finam";

export const tradingAccountsApi = {
  list: async () => {
    const { data } = await api.get("/trading-accounts");
    return data as { venues: Array<{ venue: string; title: string; description: string; connection_type: string; setup_url?: string; connected_accounts: TradingAccountOut[] }>; rotation_reminders: TradingAccountOut[] };
  },
  connect: async (body: {
    venue: ConnectRawKeyVenue;
    api_key: string;
    api_secret: string;
    account_mode?: "paper" | "live";
    no_withdrawal_confirmed?: boolean;
    base_url?: string;
  }) => {
    const { data } = await api.post("/trading-accounts/connect", body);
    return data as { ok: boolean; error?: string; account_display?: string; account?: TradingAccountOut };
  },
  connectToken: async (body: {
    venue: ConnectRawKeyVenue;
    token: string;
    account_mode?: "paper" | "live";
    no_withdrawal_confirmed?: boolean;
  }) => {
    const { data } = await api.post("/trading-accounts/connect-token", body);
    return data as { ok: boolean; error?: string; account_display?: string; account?: TradingAccountOut };
  },
  disconnect: async (venue: string, account_mode: string = "live") => {
    const { data } = await api.delete(`/trading-accounts/${venue}`, { params: { account_mode } });
    return data;
  },
};
"""
    text = text.replace("export default api;", block + "\nexport default api;")
    api.write_text(text, encoding="utf-8")
    print("api.ts updated")

settings = ROOT / "app/settings/page.tsx"
st = settings.read_text(encoding="utf-8")
if "TradingAccountsPanel" not in st:
    st = st.replace(
        'import { Save, Plus, X, AlertTriangle, Info } from "lucide-react";',
        'import { Save, Plus, X, AlertTriangle, Info } from "lucide-react";\nimport { TradingAccountsPanel } from "@/components/settings/TradingAccountsPanel";',
    )
    st = st.replace(
        "        {/* Trading mode warning */}",
        "        <TradingAccountsPanel />\n\n        {/* Trading mode warning */}",
    )
    settings.write_text(st, encoding="utf-8")
    print("settings page updated")
