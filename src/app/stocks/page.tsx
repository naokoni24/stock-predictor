import Link from "next/link";
import { supabase } from "@/lib/supabase";

const SIGNAL_LABEL: Record<string, string> = {
  buy_candidate: "買い候補",
  sell_candidate: "売り候補",
  hold: "様子見",
};

const SIGNAL_COLOR: Record<string, string> = {
  buy_candidate: "bg-green-100 text-green-800",
  sell_candidate: "bg-red-100 text-red-800",
  hold: "bg-zinc-100 text-zinc-700",
};

export default async function StocksPage() {
  const { data: stocks, error } = await supabase
    .from("stocks")
    .select("ticker, name")
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

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold">登録銘柄一覧</h1>

      {error && (
        <p className="text-red-600 text-sm">
          データ取得エラー: {error.message}
        </p>
      )}

      {!error && (!stocks || stocks.length === 0) && (
        <p className="text-zinc-500 text-sm">登録銘柄がありません。</p>
      )}

      <div className="flex flex-col gap-2">
        {(stocks ?? []).map((s) => {
          const signal = latestSignalByTicker.get(s.ticker) ?? null;
          return (
            <Link
              key={s.ticker}
              href={`/stock/${s.ticker}`}
              className="flex items-center justify-between rounded-lg border bg-white px-4 py-3 hover:bg-zinc-50"
            >
              <p className="font-semibold">
                {s.name ?? s.ticker}{" "}
                <span className="text-zinc-400 text-xs">{s.ticker}</span>
              </p>
              {signal && (
                <span
                  className={`text-xs font-semibold px-2 py-1 rounded-full ${
                    SIGNAL_COLOR[signal] ?? "bg-zinc-100 text-zinc-700"
                  }`}
                >
                  {SIGNAL_LABEL[signal] ?? "ー"}
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
