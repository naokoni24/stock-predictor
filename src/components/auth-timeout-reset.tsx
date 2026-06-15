"use client";

import { useEffect } from "react";

const AUTH_TIMEOUT_KEYS = ["lastActivityAt", "sessionStartedAt", "sessionMarker"];

export function AuthTimeoutReset() {
  useEffect(() => {
    AUTH_TIMEOUT_KEYS.forEach((key) => localStorage.removeItem(key));
  }, []);

  return null;
}
