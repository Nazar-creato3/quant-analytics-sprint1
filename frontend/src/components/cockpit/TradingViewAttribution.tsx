"use client";

/** TradingView Lightweight Charts™ attribution (license requirement). */
export function TradingViewAttribution({ className }: { className?: string }) {
  return (
    <p className={className ?? "text-[10px] text-qa-muted leading-snug"}>
      Charts powered by{" "}
      <a
        href="https://www.tradingview.com/"
        target="_blank"
        rel="noopener noreferrer"
        className="text-qa-muted hover:text-qa-text underline underline-offset-2"
      >
        TradingView Lightweight Charts™
      </a>
      . Copyright ©{" "}
      <a
        href="https://www.tradingview.com/"
        target="_blank"
        rel="noopener noreferrer"
        className="text-qa-muted hover:text-qa-text underline underline-offset-2"
      >
        TradingView
      </a>
      , Inc.
    </p>
  );
}
