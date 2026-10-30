"use client";

import { useEffect } from "react";
import { trackClientEvent } from "@/lib/product-analytics";

const PUBLIC_PREFIXES = ["/site", "/legal", "/methodology", "/support", "/login", "/signup", "/apply"];

function isPublicPath(path: string): boolean {
  return PUBLIC_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export function ProductEvents({ kind }: { kind: "user_return" | "first_report_shown" | "profile_questionnaire_completed" }) {
  useEffect(() => {
    const path = window.location.pathname;
    if (isPublicPath(path)) return;
    const key = `qa-lane2-${kind}`;
    if (kind !== "profile_questionnaire_completed" && sessionStorage.getItem(key) === "1") return;
    sessionStorage.setItem(key, "1");
    void trackClientEvent(kind);
  }, [kind]);
  return null;
}
