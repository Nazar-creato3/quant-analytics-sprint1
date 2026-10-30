"use client";

import type { ReactNode } from "react";
import { useAuth, isAdminRole } from "@/hooks";

/** Renders children only for admin-tier roles; nothing for everyone else. */
export function AdminOnlyNotice({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (!isAdminRole(user?.role)) return null;
  return <>{children}</>;
}

/** Inline technical text — admin-only, no placeholder for others. */
export function AdminOnlyText({
  text,
  className,
}: {
  text: string | null | undefined;
  className?: string;
}) {
  const { user } = useAuth();
  if (!text || !isAdminRole(user?.role)) return null;
  return <span className={className}>{text}</span>;
}
