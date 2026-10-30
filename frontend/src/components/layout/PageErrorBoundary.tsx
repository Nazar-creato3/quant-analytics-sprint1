"use client";

import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { RefreshCw } from "lucide-react";

export const PAGE_ERROR_COPY = {
  defaultTitle: "Страница временно недоступна",
  body: "Не получилось показать этот раздел. Обновите страницу или вернитесь на главную.",
  retry: "Обновить",
} as const;

export function PageErrorBoundary({
  children,
  title = PAGE_ERROR_COPY.defaultTitle,
}: {
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <ErrorBoundary
      fallback={
        <div className="min-h-[50vh] flex flex-col items-center justify-center p-8 text-center bg-cockpit-bg">
          <h2 className="text-lg font-semibold text-white mb-2">{title}</h2>
          <p className="text-sm text-qa-muted max-w-md mb-4">
            {PAGE_ERROR_COPY.body}
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="btn-primary text-xs inline-flex items-center gap-2"
          >
            <RefreshCw size={12} />
            {PAGE_ERROR_COPY.retry}
          </button>
        </div>
      }
    >
      {children}
    </ErrorBoundary>
  );
}
