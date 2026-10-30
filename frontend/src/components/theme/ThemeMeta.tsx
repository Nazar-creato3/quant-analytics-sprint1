"use client";

import { useEffect } from "react";
import { useTheme } from "@/contexts/ThemeContext";
import { readChartColors } from "@/lib/chartColors";

/** Syncs PWA theme-color meta tag with active theme tokens. */
export function ThemeMeta() {
  const { theme } = useTheme();

  useEffect(() => {
    const colors = readChartColors();
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", colors.accent);
    document.documentElement.style.colorScheme = theme === "light" ? "light" : "dark";
  }, [theme]);

  return null;
}
