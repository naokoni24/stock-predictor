export const EVALUATION_VERSION = "next_open_stop_excess_v2";
export type Outcome = {
  ticker: string;
  signal_date: string;
  outcome_date: string;
  net_return: number | null;
  ml_score: number | null;
  model_version: string;
  sector: string | null;
  evaluation_version: string | null;
};
export function dateDaysAgo(days: number, now = new Date()) {
  const date = new Date(now.getTime() - days * 86400000);
  return date.toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });
}
export function selectOutcomes(
  rows: Outcome[],
  days: number,
  now = new Date(),
) {
  const since = dateDaysAgo(days, now);
  const today = dateDaysAgo(0, now);
  return rows.filter(
    (r) =>
      r.evaluation_version === EVALUATION_VERSION &&
      r.outcome_date >= since &&
      r.outcome_date <= today &&
      r.net_return != null &&
      Number.isFinite(r.net_return),
  );
}
export function summarize(rows: Outcome[]) {
  const valid = rows.filter(
    (r) => r.net_return != null && Number.isFinite(r.net_return),
  );
  if (!valid.length) return null;
  return {
    trades: valid.length,
    winRate: valid.filter((r) => r.net_return! > 0).length / valid.length,
    netReturn: valid.reduce((sum, r) => sum + r.net_return!, 0) / valid.length,
  };
}
export function scoreBand(score: number | null) {
  if (score == null || !Number.isFinite(score) || score < 0 || score > 1)
    return "不明";
  if (score < 0.55) return "0.00〜0.55未満";
  if (score < 0.65) return "0.55〜0.65未満";
  if (score < 0.75) return "0.65〜0.75未満";
  return "0.75〜1.00";
}
export function groupOutcomes(
  rows: Outcome[],
  by: "score" | "sector" | "model",
) {
  const groups = new Map<string, Outcome[]>();
  for (const row of rows) {
    const key =
      by === "score"
        ? scoreBand(row.ml_score)
        : by === "sector"
          ? row.sector || "業種不明"
          : row.model_version || "世代不明";
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return [...groups]
    .flatMap(([label, values]) => {
      const stats = summarize(values);
      return stats ? [{ label, ...stats }] : [];
    })
    .sort((a, b) =>
      by === "score"
        ? a.label.localeCompare(b.label)
        : b.trades - a.trades || a.label.localeCompare(b.label),
    );
}
