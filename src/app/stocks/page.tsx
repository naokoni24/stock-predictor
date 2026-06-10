import { supabase } from "@/lib/supabase";
import SearchableStockList from "./SearchableStockList";

export default async function StocksPage() {
  const { data: stocks, error } = await supabase
    .from("stocks")
    .select("ticker, name, sector")
    .order("ticker");

  const tickers = (stocks ?? []).map((s) => s.ticker);

  const { data: signals } = tickers.length
    ? await supabase
        .from("signals")
        .select("ticker, date, signal")
        .in("ticker", tickers)
        .order("date", { ascending: false })
    : { data: [] };

  const latestSignalByTicker = new Map<string, string | null>();
  for (const s of signals ?? []) {
    if (!latestSignalByTicker.has(s.ticker)) {
      latestSignalByTicker.set(s.ticker, s.signal);
    }
  }

  const rows = (stocks ?? []).map((s) => ({
    ...s,
    signal: latestSignalByTicker.get(s.ticker) ?? null,
  }));

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold">登録銘柄一覧</h1>

      {error && (
        <p className="text-red-600 text-sm">
          データ取得エラー: {error.message}
        </p>
      )}

      {!error && rows.length === 0 && (
        <p className="text-zinc-500 text-sm">登録銘柄がありません。</p>
      )}

      {!error && rows.length > 0 && <SearchableStockList stocks={rows} />}
    </div>
  );
}
