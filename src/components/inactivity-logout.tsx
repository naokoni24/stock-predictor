"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase-browser";

// 一定時間操作がない場合に自動ログアウトする(Supabase Free Planでは
// Inactivity timeoutが設定できないため、クライアント側で代替実装)
const INACTIVITY_LIMIT_MS = 30 * 60 * 1000; // 30分
const STORAGE_KEY = "lastActivityAt";
const CHECK_INTERVAL_MS = 60 * 1000; // 1分ごとにチェック

const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart"] as const;

export function InactivityLogout() {
  const router = useRouter();

  useEffect(() => {
    const updateLastActivity = () => {
      localStorage.setItem(STORAGE_KEY, String(Date.now()));
    };

    updateLastActivity();
    ACTIVITY_EVENTS.forEach((event) =>
      window.addEventListener(event, updateLastActivity, { passive: true })
    );

    const interval = setInterval(async () => {
      const lastActivity = Number(localStorage.getItem(STORAGE_KEY) ?? Date.now());
      if (Date.now() - lastActivity >= INACTIVITY_LIMIT_MS) {
        clearInterval(interval);
        const supabase = createClient();
        await supabase.auth.signOut();
        router.push("/login");
        router.refresh();
      }
    }, CHECK_INTERVAL_MS);

    return () => {
      clearInterval(interval);
      ACTIVITY_EVENTS.forEach((event) =>
        window.removeEventListener(event, updateLastActivity)
      );
    };
  }, [router]);

  return null;
}
