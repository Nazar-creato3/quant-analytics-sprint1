"use client";

import { useState, useEffect } from "react";

/**
 * Stagger operator cockpit panel mounts to avoid parallel API burst on load.
 * Returns true once the given phase threshold has been reached.
 */
export function useMountPhase(phase: number, delayMs: number): boolean {
  const [ready, setReady] = useState(phase === 0);

  useEffect(() => {
    if (phase === 0) {
      setReady(true);
      return;
    }
    const timer = setTimeout(() => setReady(true), delayMs);
    return () => clearTimeout(timer);
  }, [phase, delayMs]);

  return ready;
}
