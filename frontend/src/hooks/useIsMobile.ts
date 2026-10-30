"use client";

import { useEffect, useState } from "react";

const MOBILE_BREAKPOINT = 768;

export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const update = () => setMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  return mobile;
}

/** Desktop 30s → mobile 75s default for battery/data savings. */
export function useMobilePollingInterval(desktopMs: number, mobileMs = 75_000): number {
  const isMobile = useIsMobile();
  return isMobile ? mobileMs : desktopMs;
}
