import Link from "next/link";
import { ArrowLeft, Brain, ExternalLink, TrendingDown, TrendingUp } from "lucide-react";
import { supabase } from "@/lib/supabase";
import CandlestickChart from "./CandlestickChart";
import AiScoreHistoryChart from "./AiScoreHistoryChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn, getCloseLabel } from "@/lib/utils";

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
  const historySince = new Date();
  historySince.setDate(historySince.getDate() - 420);
  const historySinceDate = historySince.toISOString().slice(0, 10);

  const [{ data: stock }, { data: prices, error }, { data: signal }, { data: scoreHistory }, { data: signalHistory }] =
    await Promise.all([
      supabase.from("stocks").select("name, sector, per, pbr, target_price, forecast_eps").eq("ticker", ticker).maybeSingle(),
      supabase
        .from("prices")
        .select("date, open, high, low, close, volume")
        .eq("ticker", ticker)
        .gte("date", historySinceDate)
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
      supabase
        .from("signals")
        .select("date, ml_score")
        .eq("ticker", ticker)
        .order("date", { ascending: false })
        .limit(60),
      supabase
        .from("signals")
        .select("date, ml_signal")
        .eq("ticker", ticker)
        .gte("date", historySinceDate)
        .order("date", { ascending: true }),
    ]);

  // AI予測（買い候補）の的中率: シグナル発生から5営業日後に終値が上昇していたか
  const HIT_RATE_HORIZON = 5;
  const hitRate = (() => {
    if (!prices || !signalHistory) return null;
    const dateIndex = new Map(prices.map((p, i) => [p.date, i]));
    let wins = 0;
    let total = 0;
    for (const s of signalHistory) {
      if (s.ml_signal !== "buy_candidate") continue;
      const idx = dateIndex.get(s.date);
      if (idx == null) continue;
      const future = prices[idx + HIT_RATE_HORIZON];
      // closeがnull(yfinanceの未確定/低調日)の場合、null(=0扱い)との比較で
      // 的中率が不正に水増しされる不具合があったため、両方の終値が有効な場合のみ集計する。
      if (!future || future.close == null || prices[idx].close == null) continue;
      total += 1;
      if (future.close > prices[idx].close) wins += 1;
    }
    return total > 0 ? { rate: (wins / total) * 100, total } : null;
  })();

  // yfinanceが当日終値をまだ確定配信していない日はcloseがnullで保存されるため、
  // ヘッダーの現在値・前日比には直近の有効な終値を使う(latest.close?.toLocaleString()
  // だとnullでクラッシュしていた不具合の修正を兼ねる)。
  const pricesWithClose = (prices ?? []).filter((p) => p.close != null);
  const latest = pricesWithClose[pricesWithClose.length - 1];
  const prev = pricesWithClose[pricesWithClose.length - 2];
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
            <a
              href={`https://finance.yahoo.co.jp/quote/${ticker}`}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent"
            >
              <ExternalLink className="size-3.5" />
              Yahoo!ファイナンスで詳細を見る
            </a>
          </div>
          {latest && (
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-[10px] text-muted-foreground">{getCloseLabel(latest.date)}</span>
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

          {scoreHistory && scoreHistory.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">AI予測スコアの推移</CardTitle>
              </CardHeader>
              <CardContent>
                <AiScoreHistoryChart data={[...scoreHistory].reverse()} />
              </CardContent>
            </Card>
          )}

          {stock && (stock.per != null || stock.pbr != null || stock.target_price != null) && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">ファンダメンタル指標</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
                  <div className="flex flex-col">
                    <IndicatorRow label="PER(予想)" value={stock.per != null ? `${stock.per.toFixed(1)}倍` : "ー"} />
                    <Separator />
                    <IndicatorRow label="PBR" value={stock.pbr != null ? `${stock.pbr.toFixed(2)}倍` : "ー"} />
                  </div>
                  <div className="flex flex-col">
                    <IndicatorRow
                      label="アナリスト目標株価"
                      value={stock.target_price != null ? `¥${Math.round(stock.target_price).toLocaleString()}` : "ー"}
                    />
                    <Separator />
                    <IndicatorRow label="予想EPS" value={stock.forecast_eps != null ? `¥${stock.forecast_eps.toFixed(2)}` : "ー"} />
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

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

              {hitRate && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">
                    AI買い予測の的中率({HIT_RATE_HORIZON}日後上昇・{hitRate.total}件)
                  </span>
                  <span
                    className={cn(
                      "font-semibold tabular-nums",
                      hitRate.rate >= 50 ? "text-bullish" : "text-bearish"
                    )}
                  >
                    {hitRate.rate.toFixed(0)}%
                  </span>
                </div>
              )}

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
