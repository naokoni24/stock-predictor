type Price = { date: string; close: number | null };
type Signal = { date: string; ml_signal: string | null };

/** 市場共通の取引日で5営業日後を特定する。個別銘柄の欠損で評価日を延長しない。 */
export function calculateHitRate(prices: Price[], signals: Signal[], tradingDates: string[], horizon = 5) {
  const calendar = [...new Set(tradingDates)].sort();
  const dateIndex = new Map(calendar.map((date, i) => [date, i]));
  const closeByDate = new Map(prices.map((price) => [price.date, price.close]));
  let wins = 0;
  let total = 0;
  for (const signal of signals) {
    if (signal.ml_signal !== "buy_candidate") continue;
    const index = dateIndex.get(signal.date);
    if (index == null) continue;
    const futureDate = calendar[index + horizon];
    if (!futureDate) continue;
    const entry = closeByDate.get(signal.date);
    const exit = closeByDate.get(futureDate);
    if (entry == null || exit == null || !Number.isFinite(entry) || !Number.isFinite(exit) || entry <= 0 || exit <= 0) continue;
    total += 1;
    if (exit > entry) wins += 1;
  }
  return total > 0 ? { rate: wins / total * 100, total } : null;
}
