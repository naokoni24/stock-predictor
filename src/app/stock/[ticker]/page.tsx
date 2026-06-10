import Link from "next/link";
import { supabase } from "@/lib/supabase";
import PriceChart from "./PriceChart";

const SIGNAL_LABEL: Record<string, string> = {
  buy_candidate: "買い候補",
  sell_candidate: "売り候補",
  hold: "様子見",
};

export default async function StockDetail({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;

  const [{ data: stock }, { data: prices, error }, { data: signal }] =
    await Promise.all([
      supabase.from("stocks").select("name").eq("ticker", ticker).maybeSingle(),
      supabase
        .from("prices")
        .select("date, close")
        .eq("ticker", ticker)
        .order("date", { ascending: true }),
      supabase
        .from("signals")
        .select(
          "close, sma25, sma75, rsi14, macd, macd_signal, bb_upper, bb_lower, signal, score, date"
        )
        .eq("ticker", ticker)
        .order("date", { ascending: false })
        .limit(1)
        .maybeSingle(),
    ]);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          ← 本日のおすすめに戻る
        </Link>
        <h1 className="text-xl font-bold mt-1">
          {stock?.name ?? ticker}{" "}
          <span className="text-zinc-400 text-sm">{ticker}</span>
        </h1>
      </div>

      {error && (
        <p className="text-red-600 text-sm">
          データ取得エラー: {error.message}
        </p>
      )}

      {!error && (!prices || prices.length === 0) && (
        <p className="text-zinc-500 text-sm">価格データがありません。</p>
      )}

      {prices && prices.length > 0 && <PriceChart data={prices} />}

      {signal && (
        <div className="rounded-lg border bg-white p-4 text-sm grid grid-cols-2 gap-y-2 gap-x-4">
          <span className="text-zinc-500">シグナル</span>
          <span className="font-semibold">
            {SIGNAL_LABEL[signal.signal ?? ""] ?? "ー"}（スコア {signal.score}）
          </span>
          <span className="text-zinc-500">終値</span>
          <span>{signal.close?.toLocaleString()} 円</span>
          <span className="text-zinc-500">SMA25 / SMA75</span>
          <span>
            {signal.sma25?.toFixed(1)} / {signal.sma75?.toFixed(1)}
          </span>
          <span className="text-zinc-500">RSI14</span>
          <span>{signal.rsi14?.toFixed(1)}</span>
          <span className="text-zinc-500">MACD / シグナル線</span>
          <span>
            {signal.macd?.toFixed(2)} / {signal.macd_signal?.toFixed(2)}
          </span>
          <span className="text-zinc-500">ボリンジャーバンド(上/下)</span>
          <span>
            {signal.bb_upper?.toFixed(1)} / {signal.bb_lower?.toFixed(1)}
          </span>
          <span className="text-zinc-500">最終更新</span>
          <span>{signal.date}</span>
        </div>
      )}
    </div>
  );
}
