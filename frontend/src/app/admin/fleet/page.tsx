"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AdminFleetRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/operator/admissions/accounts");
  }, [router]);
  return null;
}
