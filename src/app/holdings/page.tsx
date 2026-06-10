import Link from "next/link";
import { supabase } from "@/lib/supabase";
import HoldingsForm from "./HoldingsForm";
import DeleteHoldingButton from "./DeleteHoldingButton";

export default async function HoldingsPage() {
  const { data: holdings, error } = await supabase
    .from("holdings")
    .select("id, ticker, shares, cost_price, stocks(name)")
    .order("id");

  const tickers = (holdings ?? []).map((h) => h.ticker);

  const { data: latestSignals } = tickers.length
    ? await supabase
        .from("signals")
        .select("ticker, date, close, signal")
        .in("ticker", tickers)
        .order("date", { ascending: false })
    : { data: [] };

  // 各銘柄の最新シグナルのみ残す
  const latestByTicker = new Map<string, { close: number; signal: string | null }>();
  for (const s of latestSignals ?? []) {
    if (!latestByTicker.has(s.ticker)) {
      latestByTicker.set(s.ticker, { close: s.close, signal: s.signal });
    }
  }

  const rows = (holdings ?? []).map((h) => {
    const stockName = Array.isArray(h.stocks) ? h.stocks[0]?.name : (h.stocks as { name: string } | null)?.name;
    const latest = latestByTicker.get(h.ticker);
    const currentPrice = latest?.close ?? null;
    const profitRate = currentPrice
      ? ((currentPrice - h.cost_price) / h.cost_price) * 100
      : null;

    return {
      ...h,
      stockName,
      currentPrice,
      profitRate,
      signal: latest?.signal ?? null,
    };
  });

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold">保有株一覧</h1>

      <HoldingsForm />

      {error && (
        <p className="text-red-600 text-sm">
          データ取得エラー: {error.message}
        </p>
      )}

      {!error && rows.length === 0 && (
        <p className="text-zinc-500 text-sm">
          保有株が登録されていません。Supabaseのholdingsテーブルに登録してください。
        </p>
      )}

      <div className="flex flex-col gap-2">
        {rows.map((h) => (
          <div
            key={h.id}
            className="flex items-center justify-between rounded-lg border bg-white px-4 py-3"
          >
            <div>
              <Link
                href={`/stock/${h.ticker}`}
                className="font-semibold hover:underline"
              >
                {h.stockName ?? h.ticker}{" "}
                <span className="text-zinc-400 text-xs">{h.ticker}</span>
              </Link>
              <p className="text-sm text-zinc-500">
                {h.shares}株 / 取得単価 {h.cost_price.toLocaleString()}円
                {h.currentPrice != null && (
                  <>
                    {" "}
                    / 現在値 {h.currentPrice.toLocaleString()}円 (
                    <span
                      className={
                        (h.profitRate ?? 0) >= 0
                          ? "text-green-600"
                          : "text-red-600"
                      }
                    >
                      {h.profitRate?.toFixed(1)}%
                    </span>
                    )
                  </>
                )}
              </p>
            </div>
            <div className="flex items-center gap-3">
              {h.signal === "sell_candidate" && (
                <span className="text-xs font-semibold px-2 py-1 rounded-full bg-red-100 text-red-800">
                  売り時候補
                </span>
              )}
              <DeleteHoldingButton id={h.id} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
