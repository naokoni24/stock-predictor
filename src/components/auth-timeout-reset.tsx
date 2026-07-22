"use client";

import { useEffect } from "react";

const AUTH_TIMEOUT_KEYS = ["lastActivityAt", "sessionStartedAt", "sessionMarker"];
const BROWSER_SESSION_KEY = "authBrowserSession";

export function AuthTimeoutReset() {
  useEffect(() => {
    AUTH_TIMEOUT_KEYS.forEach((key) => localStorage.removeItem(key));
    // ログイン画面を開いたタブだけを認証済みセッションとして扱う。
    // sessionStorage はタブを閉じると消えるため、次回ブラウザを開いた際に
    // 古いSupabase Cookieだけでログイン状態が復元されるのを防ぐ。
    sessionStorage.setItem(BROWSER_SESSION_KEY, "active");
  }, []);

  return null;
}
