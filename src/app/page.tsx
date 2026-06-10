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

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}) {
  const { tab } = await searchParams;
  const signalType = tab === "sell" ? "sell_candidate" : "buy_candidate";

  const { data: signals, error } = await supabase
    .from("signals")
    .select("ticker, date, close, rsi14, signal, score, ml_signal, ml_score, stocks(name, sector)")
    .eq("signal", signalType)
    .order("date", { ascending: false })
    .order("score", { ascending: signalType === "sell_candidate" })
    .limit(10);

  const rows = (signals ?? []).map((s) => {
    const stock = Array.isArray(s.stocks) ? s.stocks[0] : s.stocks;
    return {
      ...s,
      stockName: stock?.name,
      sector: stock?.sector,
    };
  });

  const tabClass = (active: boolean) =>
    `px-4 py-2 text-sm font-medium border-b-2 ${
      active
        ? "border-zinc-900 text-zinc-900"
        : "border-transparent text-zinc-400 hover:text-zinc-600"
    }`;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold">本日のおすすめ</h1>

      <div className="flex border-b">
        <Link href="/" className={tabClass(signalType === "buy_candidate")}>
          買い候補
        </Link>
        <Link
          href="/?tab=sell"
          className={tabClass(signalType === "sell_candidate")}
        >
          売り候補
        </Link>
      </div>

      {error && (
        <p className="text-red-600 text-sm">
          データ取得エラー: {error.message}
        </p>
      )}

      {!error && (!signals || signals.length === 0) && (
        <p className="text-zinc-500 text-sm">
          該当する銘柄がありません。
        </p>
      )}

      <div className="flex flex-col gap-2">
        {rows.map((s) => (
          <Link
            key={s.ticker}
            href={`/stock/${s.ticker}`}
            className="flex items-center justify-between rounded-lg border bg-white px-4 py-3 hover:bg-zinc-50"
          >
            <div>
              <p className="font-semibold">
                {s.stockName ?? s.ticker}{" "}
                <span className="text-zinc-400 text-xs">{s.ticker}</span>
              </p>
              <p className="text-sm text-zinc-500">
                終値 {s.close?.toLocaleString()} 円 / RSI {s.rsi14?.toFixed(1)}
                {s.sector && ` / ${s.sector}`}
                {s.ml_score != null && ` / AI上昇期待度 ${(s.ml_score * 100).toFixed(0)}%`}
              </p>
            </div>
            <div className="flex flex-col items-end gap-1">
              <span
                className={`text-xs font-semibold px-2 py-1 rounded-full ${
                  SIGNAL_COLOR[s.signal ?? ""] ?? "bg-zinc-100 text-zinc-700"
                }`}
              >
                {SIGNAL_LABEL[s.signal ?? ""] ?? "ー"}
              </span>
              {s.ml_signal === "buy_candidate" && (
                <span className="text-xs font-semibold px-2 py-1 rounded-full bg-blue-100 text-blue-800">
                  AI買い候補
                </span>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
