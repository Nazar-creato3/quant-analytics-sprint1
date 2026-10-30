"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AUTH_SESSION_CHANGED_EVENT, userQueryKey } from "@/lib/user-scoped-query";
import { useAuth } from "@/hooks";

/** Stable per-user query key prefix + cross-tab session invalidation. */
export function useUserQueryScope() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const userKey = user?.email?.toLowerCase() ?? user?.id ?? undefined;

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === "access_token") {
        queryClient.clear();
      }
    };
    const onSessionChanged = () => {
      queryClient.clear();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(AUTH_SESSION_CHANGED_EVENT, onSessionChanged);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(AUTH_SESSION_CHANGED_EVENT, onSessionChanged);
    };
  }, [queryClient]);

  return {
    userKey,
    scopedKey: (...parts: readonly unknown[]) => userQueryKey(userKey, ...parts),
  };
}
