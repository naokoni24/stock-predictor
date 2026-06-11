import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * 終値の日付が日本時間の本日であれば「当日終値」、それ以外は「前日終値」を返す。
 * (株価データは平日16:30頃に更新されるため、当日分が反映されていれば「当日終値」となる)
 */
export function getCloseLabel(date: string): string {
  const today = new Date().toLocaleDateString("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).replace(/\//g, "-");

  return date === today ? "当日終値" : "前日終値";
}
