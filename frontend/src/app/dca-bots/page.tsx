"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function DcaBotsRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/bots");
  }, [router]);
  return null;
}
