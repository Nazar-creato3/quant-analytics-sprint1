"use client";

import { Toaster } from "react-hot-toast";
import { useTheme } from "@/contexts/ThemeContext";
import { useChartColors } from "@/hooks/useChartColors";

/** Toast styling that follows active theme tokens. */
export function ThemeToaster() {
  const { theme } = useTheme();
  const colors = useChartColors();

  return (
    <Toaster
      key={theme}
      position="bottom-right"
      toastOptions={{
        style: {
          background: colors.crosshairLabel,
          color: colors.liveNeutral,
          border: `1px solid ${colors.border}`,
          fontSize: "13px",
          fontFamily: "var(--font-inter)",
        },
        success: {
          iconTheme: { primary: colors.success, secondary: colors.crosshairLabel },
          duration: 4000,
        },
        error: {
          iconTheme: { primary: colors.danger, secondary: colors.crosshairLabel },
          duration: 6000,
        },
      }}
    />
  );
}
