import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * 当日以外は実際の日付を表示する。数日前の価格を「前日終値」と誤表示しない。
 */
export function getCloseLabel(date: string): string {
  const today = new Date().toLocaleDateString("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).replace(/\//g, "-");

  return date === today ? "当日終値" : `${date.slice(5).replace("-", "/")} 終値`;
}
