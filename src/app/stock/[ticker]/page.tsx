import Link from "next/link";
import { ArrowLeft, Brain, TrendingDown, TrendingUp } from "lucide-react";
import { supabase } from "@/lib/supabase";
import CandlestickChart from "./CandlestickChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

const SIGNAL_LABEL: Record<string, string> = {
  buy_candidate: "買い候補",
  sell_candidate: "売り候補",
  hold: "様子見",
};

function IndicatorRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
    </div>
  );
}

export default async function StockDetail({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;

  const [{ data: stock }, { data: prices, error }, { data: signal }] =
    await Promise.all([
      supabase.from("stocks").select("name, sector").eq("ticker", ticker).maybeSingle(),
      supabase
        .from("prices")
        .select("date, open, high, low, close, volume")
        .eq("ticker", ticker)
        .order("date", { ascending: true }),
      supabase
        .from("signals")
        .select(
          "close, sma25, sma75, rsi14, macd, macd_signal, bb_upper, bb_lower, signal, score, ml_signal, ml_score, date"
        )
        .eq("ticker", ticker)
        .order("date", { ascending: false })
        .limit(1)
        .maybeSingle(),
    ]);

  const latest = prices?.[prices.length - 1];
  const prev = prices?.[prices.length - 2];
  const changePct =
    latest && prev && prev.close ? ((latest.close - prev.close) / prev.close) * 100 : null;

  const aiScore = signal?.ml_score ?? null;
  const isBullish = (aiScore ?? 0.5) >= 0.5;
  const recommendation =
    signal?.signal === "buy_candidate" && signal?.ml_signal === "buy_candidate"
      ? "buy"
      : signal?.signal === "sell_candidate"
        ? "sell"
        : signal?.ml_signal === "buy_candidate"
          ? "buy"
          : "hold";

  const RECOMMENDATION_CONFIG = {
    buy: { label: "買い", className: "bg-bullish text-bullish-foreground" },
    sell: { label: "売り", className: "bg-bearish text-bearish-foreground" },
    hold: { label: "様子見", className: "bg-secondary text-secondary-foreground" },
  } as const;

  const explanation = (() => {
    const parts: string[] = [];
    if (signal?.signal && SIGNAL_LABEL[signal.signal]) {
      parts.push(`テクニカル指標は「${SIGNAL_LABEL[signal.signal]}」を示しています。`);
    }
    if (signal?.rsi14 != null) {
      if (signal.rsi14 >= 70) parts.push(`RSIは${signal.rsi14.toFixed(1)}と買われすぎ水準です。`);
      else if (signal.rsi14 <= 30) parts.push(`RSIは${signal.rsi14.toFixed(1)}と売られすぎ水準です。`);
      else parts.push(`RSIは${signal.rsi14.toFixed(1)}で中立圏です。`);
    }
    if (aiScore != null) {
      parts.push(`AIモデルは今後の上昇確率を${(aiScore * 100).toFixed(0)}%と予測しています。`);
    }
    if (signal?.sma25 != null && signal?.sma75 != null && signal?.close != null) {
      if (signal.close > signal.sma25 && signal.sma25 > signal.sma75) {
        parts.push("短期・中期の移動平均線は上向きのトレンドを形成しています。");
      } else if (signal.close < signal.sma25 && signal.sma25 < signal.sma75) {
        parts.push("短期・中期の移動平均線は下向きのトレンドを形成しています。");
      }
    }
    return parts.join("");
  })();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          本日のおすすめに戻る
        </Link>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {stock?.name ?? ticker}{" "}
              <span className="text-muted-foreground text-base font-normal">{ticker}</span>
            </h1>
            {stock?.sector && <p className="text-sm text-muted-foreground mt-0.5">{stock.sector}</p>}
          </div>
          {latest && (
            <div className="flex flex-col items-end gap-0.5">
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold tabular-nums">¥{latest.close.toLocaleString()}</span>
                {changePct != null && (
                  <span
                    className={cn(
                      "flex items-center gap-0.5 text-sm font-medium tabular-nums",
                      changePct >= 0 ? "text-bullish" : "text-bearish"
                    )}
                  >
                    {changePct >= 0 ? <TrendingUp className="size-4" /> : <TrendingDown className="size-4" />}
                    {changePct >= 0 ? "+" : ""}
                    {changePct.toFixed(2)}%
                  </span>
                )}
              </div>
              <span className="text-[10px] text-muted-foreground">前日終値</span>
            </div>
          )}
        </div>
      </div>

      {error && <p className="text-bearish text-sm">データ取得エラー: {error.message}</p>}

      {!error && (!prices || prices.length === 0) && (
        <p className="text-muted-foreground text-sm">価格データがありません。</p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 flex flex-col gap-6">
          {prices && prices.length > 0 && <CandlestickChart data={prices} />}

          {signal && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">テクニカル指標</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
                  <div className="flex flex-col">
                    <IndicatorRow label="SMA25" value={signal.sma25?.toFixed(1) ?? "ー"} />
                    <Separator />
                    <IndicatorRow label="SMA75" value={signal.sma75?.toFixed(1) ?? "ー"} />
                    <Separator />
                    <IndicatorRow label="RSI14" value={signal.rsi14?.toFixed(1) ?? "ー"} />
                  </div>
                  <div className="flex flex-col">
                    <IndicatorRow
                      label="MACD / シグナル線"
                      value={`${signal.macd?.toFixed(2) ?? "ー"} / ${signal.macd_signal?.toFixed(2) ?? "ー"}`}
                    />
                    <Separator />
                    <IndicatorRow
                      label="ボリンジャーバンド(上/下)"
                      value={`${signal.bb_upper?.toFixed(1) ?? "ー"} / ${signal.bb_lower?.toFixed(1) ?? "ー"}`}
                    />
                    <Separator />
                    <IndicatorRow label="最終更新" value={signal.date} />
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Brain className="size-4" />
                AI分析
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">推奨アクション</span>
                <Badge className={RECOMMENDATION_CONFIG[recommendation].className}>
                  {RECOMMENDATION_CONFIG[recommendation].label}
                </Badge>
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">上昇確率(AI予測)</span>
                  <span className={cn("font-semibold tabular-nums", isBullish ? "text-bullish" : "text-bearish")}>
                    {aiScore != null ? `${(aiScore * 100).toFixed(0)}%` : "ー"}
                  </span>
                </div>
                {aiScore != null && (
                  <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
                    <div
                      className={cn("h-full rounded-full", isBullish ? "bg-bullish" : "bg-bearish")}
                      style={{ width: `${Math.round(aiScore * 100)}%` }}
                    />
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">テクニカルスコア</span>
                <span className="font-semibold tabular-nums">{signal?.score ?? "ー"}</span>
              </div>

              <Separator />

              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1.5">AI解説</p>
                <p className="text-sm leading-relaxed">
                  {explanation || "現在分析中のデータがありません。"}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
