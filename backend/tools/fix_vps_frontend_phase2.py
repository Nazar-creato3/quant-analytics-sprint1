"""Patch frontend for Direct Deals no-key banner and trading status API."""
from __future__ import annotations

from pathlib import Path

FRONT = Path("/home/user1/myapp/frontend/src")


def patch_api(content: str) -> str:
    if "tradingKeyStatus" in content:
        return content
    block = """
  tradingKeyStatus: async () => {
    const { data } = await api.get("/trading-accounts/status");
    return data as { has_any_key: boolean; connected_venues: string[]; settings_path: string };
  },
"""
    return content.replace(
        "  disconnect: async (venue: string, account_mode: string = \"live\") => {",
        block + "  disconnect: async (venue: string, account_mode: string = \"live\") => {",
    )


def patch_direct_deals(content: str) -> str:
    if "NoTradingKeyBanner" in content:
        return content
    content = content.replace(
        'import { marketApi, ordersApi, portfolioApi } from "@/lib/api";',
        'import { marketApi, ordersApi, portfolioApi, tradingAccountsApi } from "@/lib/api";\n'
        'import { NoTradingKeyBanner } from "@/components/settings/TradingAccountsPanel";',
    )
    # Add query after exports function - find first useQuery block
    hook = """
  const { data: tradingKeyStatus } = useQuery({
    queryKey: ["trading-key-status"],
    queryFn: tradingAccountsApi.tradingKeyStatus,
    staleTime: 60_000,
  });
"""
    content = content.replace(
        "  const maneuverId = urlParams.maneuverId;",
        hook + "\n  const maneuverId = urlParams.maneuverId;",
    )
    banner = """
        {!tradingKeyStatus?.has_any_key ? (
          <div className="px-4 pt-3">
            <NoTradingKeyBanner />
          </div>
        ) : null}
"""
    content = content.replace(
        "<DirectDealsInstrumentTabs",
        banner + "\n        <DirectDealsInstrumentTabs",
        1,
    )
    return content


def main() -> None:
    api = FRONT / "lib/api.ts"
    dd = FRONT / "components/direct-deals/DirectDealsView.tsx"
    for path, fn in [(api, patch_api), (dd, patch_direct_deals)]:
        text = path.read_text(encoding="utf-8")
        updated = fn(text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            print("PATCHED", path)
        else:
            print("OK", path)


if __name__ == "__main__":
    main()
