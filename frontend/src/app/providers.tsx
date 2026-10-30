"use client";

import { Suspense, useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { bootstrapAuthSession } from "@/lib/api";
import { syncAuthFromCookie } from "@/lib/auth-sync";
import { StylesheetHealthCheck } from "@/components/layout/StylesheetHealthCheck";
import { DashboardModeProvider } from "@/contexts/DashboardModeContext";
import { ActiveTickerProvider } from "@/contexts/ActiveTickerContext";
import { ProductProvider } from "@/contexts/ProductContext";
import { ActiveTickerJump } from "@/components/terminal/ActiveTickerJump";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { LocaleProvider } from "@/contexts/LocaleContext";
import { ThemeToaster } from "@/components/theme/ThemeToaster";
import { ThemeMeta } from "@/components/theme/ThemeMeta";
import { OnboardingProvider } from "@/components/onboarding/OnboardingProvider";
import { Spinner } from "@/components/ui";
import { useUserQueryScope } from "@/hooks/useUserQueryScope";
import { ProductEvents } from "@/components/analytics/ProductEvents";

/** Clears React Query cache on login/logout and cross-tab token changes. */
function UserQueryScopeSync() {
  useUserQueryScope();
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    syncAuthFromCookie();
    void bootstrapAuthSession();
  }, []);

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <UserQueryScopeSync />
      <StylesheetHealthCheck />
      <Suspense
        fallback={
          <div className="min-h-screen flex items-center justify-center bg-cockpit-bg">
            <Spinner size={24} />
          </div>
        }
      >
        <ThemeProvider>
          <LocaleProvider>
          <DashboardModeProvider>
            <ActiveTickerProvider>
              <ProductProvider>
              <OnboardingProvider>
                {children}
                <ProductEvents kind="user_return" />
                <ActiveTickerJump />
              </OnboardingProvider>
              </ProductProvider>
            </ActiveTickerProvider>
          </DashboardModeProvider>
          <ThemeMeta />
          <ThemeToaster />
          </LocaleProvider>
        </ThemeProvider>
      </Suspense>
    </QueryClientProvider>
  );
}
