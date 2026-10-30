"use client";

import { useMemo } from "react";
import { useTheme } from "@/contexts/ThemeContext";
import { readChartColors, type ChartColorPalette } from "@/lib/chartColors";

/** Chart palette that refreshes when the user switches light/dark theme. */
export function useChartColors(): ChartColorPalette {
  const { theme } = useTheme();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- theme triggers DOM token re-read
  return useMemo(() => readChartColors(), [theme]);
}
