"use client";

import { clsx } from "clsx";
import { useEffect, useState } from "react";

type ThemeLogoProps = {
  width?: number;
  height?: number;
  className?: string;
  priority?: boolean;
  alt?: string;
};

/** Theme-aware QA shield crest — brand PNG with transparent background, no container box. */
export function ThemeLogo({
  width = 56,
  height = 56,
  className,
  priority = false,
  alt = "Quant Analytics",
}: ThemeLogoProps) {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    const root = document.documentElement;
    const read = () => {
      const attr = root.getAttribute("data-theme");
      if (attr === "light" || attr === "dark") {
        setTheme(attr);
        return;
      }
      setTheme(root.classList.contains("light") ? "light" : "dark");
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme", "class"] });
    return () => observer.disconnect();
  }, []);

  const src =
    theme === "light" ? "/shield-black-transparent.png" : "/shield-white-transparent.png";

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      width={width}
      height={height}
      decoding="async"
      fetchPriority={priority ? "high" : "auto"}
      className={clsx("object-contain shrink-0 bg-transparent", className)}
      style={{
        width,
        height,
        maxWidth: width,
        maxHeight: height,
        // Sharper downscale for detailed crest at nav/login sizes (458×709 source PNG).
        imageRendering: "-webkit-optimize-contrast",
      }}
    />
  );
}
