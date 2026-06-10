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

export default async function Home() {
  const { data: signals, error } = await supabase
    .from("signals")
    .select("ticker, date, close, rsi14, signal, score, stocks(name)")
    .eq("signal", "buy_candidate")
    .order("date", { ascending: false })
    .order("score", { ascending: false })
    .limit(10);

  const rows = (signals ?? []).map((s) => ({
    ...s,
    stockName: Array.isArray(s.stocks) ? s.stocks[0]?.name : s.stocks?.name,
  }));

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold">本日のおすすめ</h1>

      {error && (
        <p className="text-red-600 text-sm">
          データ取得エラー: {error.message}
        </p>
      )}

      {!error && (!signals || signals.length === 0) && (
        <p className="text-zinc-500 text-sm">
          まだデータがありません。スクリプトを実行してシグナルを生成してください。
        </p>
      )}

      <div className="flex flex-col gap-2">
        {rows.map((s) => (
          <div
            key={s.ticker}
            className="flex items-center justify-between rounded-lg border bg-white px-4 py-3"
          >
            <div>
              <p className="font-semibold">
                {s.stockName ?? s.ticker}{" "}
                <span className="text-zinc-400 text-xs">{s.ticker}</span>
              </p>
              <p className="text-sm text-zinc-500">
                終値 {s.close?.toLocaleString()} 円 / RSI {s.rsi14?.toFixed(1)}
              </p>
            </div>
            <span
              className={`text-xs font-semibold px-2 py-1 rounded-full ${
                SIGNAL_COLOR[s.signal ?? ""] ?? "bg-zinc-100 text-zinc-700"
              }`}
            >
              {SIGNAL_LABEL[s.signal ?? ""] ?? "ー"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
