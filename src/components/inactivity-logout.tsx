"use client";

import { useEffect } from "react";
import { createClient } from "@/lib/supabase-browser";

// 一定時間操作がない場合に自動ログアウトする(Supabase Free Planでは
// Inactivity timeoutが設定できないため、クライアント側で代替実装)
const INACTIVITY_LIMIT_MS = 30 * 60 * 1000; // 30分
const SESSION_LIMIT_MS = 12 * 60 * 60 * 1000; // ログインから最大12時間
const LAST_ACTIVITY_KEY = "lastActivityAt";
const SESSION_STARTED_KEY = "sessionStartedAt";
const SESSION_MARKER_KEY = "sessionMarker";
const CHECK_INTERVAL_MS = 60 * 1000; // 1分ごとにチェック

const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart"] as const;

export function InactivityLogout() {
  useEffect(() => {
    const supabase = createClient();
    let interval: ReturnType<typeof setInterval> | null = null;
    let signedOut = false;

    const clearStoredSession = () => {
      localStorage.removeItem(LAST_ACTIVITY_KEY);
      localStorage.removeItem(SESSION_STARTED_KEY);
      localStorage.removeItem(SESSION_MARKER_KEY);
    };

    const signOutForTimeout = async () => {
      if (signedOut) return true;
      signedOut = true;
      if (interval) clearInterval(interval);
      // 既に描画済みのタブに戻ってきた場合(focus/visibilitychange等)は描画前スクリプトが
      // 走らないため、ここで即座にコンテンツを隠す。signOut/リロード完了まで旧画面を見せない。
      document.documentElement.setAttribute("data-auth-expired", "");
      clearStoredSession();
      // scope:"local" はサーバーへの失効リクエスト(ネットワーク往復)を行わず、
      // ローカルのCookie/セッションのみ即時クリアする。遷移までの時間を短縮する。
      await supabase.auth.signOut({ scope: "local" });
      // クライアント遷移だと data-auth-expired が残りログイン画面まで隠れるため、
      // フルリロードで /login へ遷移する(隠したままログイン画面に切り替わる)。
      window.location.replace("/login");
      return true;
    };

    const ensureSessionTracking = async () => {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const now = Date.now();
      const marker = session?.user.id ?? "no-session";

      if (localStorage.getItem(SESSION_MARKER_KEY) !== marker) {
        localStorage.setItem(SESSION_MARKER_KEY, marker);
        localStorage.setItem(SESSION_STARTED_KEY, String(now));
        localStorage.setItem(LAST_ACTIVITY_KEY, String(now));
        return;
      }

      if (!localStorage.getItem(SESSION_STARTED_KEY)) {
        localStorage.setItem(SESSION_STARTED_KEY, String(now));
      }
      if (!localStorage.getItem(LAST_ACTIVITY_KEY)) {
        localStorage.setItem(LAST_ACTIVITY_KEY, String(now));
      }
    };

    // localStorageのタイムスタンプだけで同期判定する(getSession不要=即時に判定できる)
    const isExpired = () => {
      const now = Date.now();
      const sessionStarted = Number(localStorage.getItem(SESSION_STARTED_KEY) ?? now);
      const lastActivity = Number(localStorage.getItem(LAST_ACTIVITY_KEY) ?? now);
      return (
        now - sessionStarted >= SESSION_LIMIT_MS ||
        now - lastActivity >= INACTIVITY_LIMIT_MS
      );
    };

    const checkTimeout = async () => {
      if (signedOut) return true;
      if (isExpired()) {
        return signOutForTimeout();
      }
      // 期限内なら、描画前スクリプトが付けた非表示フラグを解除して表示する
      document.documentElement.removeAttribute("data-auth-expired");
      return false;
    };

    const updateLastActivity = () => {
      void checkTimeout().then((timedOut) => {
        if (!timedOut) {
          localStorage.setItem(LAST_ACTIVITY_KEY, String(Date.now()));
        }
      });
    };

    // 期限切れなら getSession を待たず即座にログアウトする(黒画面の時間を最短化)。
    if (isExpired()) {
      void signOutForTimeout();
      return;
    }
    void ensureSessionTracking().then(checkTimeout);
    ACTIVITY_EVENTS.forEach((event) =>
      window.addEventListener(event, updateLastActivity, { passive: true })
    );

    interval = setInterval(checkTimeout, CHECK_INTERVAL_MS);

    // バックグラウンドタブではsetIntervalが遅延・停止することがあるため、
    // タブがフォアグラウンドに戻ったタイミングでも即座にチェックする
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void checkTimeout();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", checkTimeout);
    window.addEventListener("pageshow", checkTimeout);

    return () => {
      if (interval) clearInterval(interval);
      ACTIVITY_EVENTS.forEach((event) =>
        window.removeEventListener(event, updateLastActivity)
      );
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", checkTimeout);
      window.removeEventListener("pageshow", checkTimeout);
    };
  }, []);

  return null;
}
