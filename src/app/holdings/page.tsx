import Link from "next/link";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Wallet } from "lucide-react";
import { createClient } from "@/lib/supabase-server";
import HoldingsForm from "./HoldingsForm";
import AllocationChart from "./AllocationChart";
import DeleteHoldingButton from "./DeleteHoldingButton";
import DismissibleAlert from "./DismissibleAlert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn, getCloseLabel } from "@/lib/utils";

// 損益アラートの閾値（%）
const LOSS_ALERT_THRESHOLD = -10;
const GAIN_ALERT_THRESHOLD = 15;

// 推奨損切り幅（取得単価からの下落率）。バックテストで-8%が好成績(リターン維持しつつ最大DD/最悪トレード削減)。
const STOP_LOSS_PCT = 0.08;

function riskLevel(rsi14: number | null, profitRate: number | null) {
  let score = 30;
  if (rsi14 != null) {
    if (rsi14 >= 70 || rsi14 <= 30) score += 35;
    else if (rsi14 >= 60 || rsi14 <= 40) score += 15;
  }
  if (profitRate != null && profitRate <= -10) score += 25;
  score = Math.min(score, 100);

  if (score >= 65) return { label: "高", score, className: "bg-bearish text-bearish-foreground" };
  if (score >= 40) return { label: "中", score, className: "bg-secondary text-secondary-foreground" };
  return { label: "低", score, className: "bg-bullish text-bullish-foreground" };
}

export default async function HoldingsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; success?: string }>;
}) {
  const { error: formError, success } = await searchParams;
  const supabase = await createClient();

  const { data: holdings, error } = await supabase
    .from("holdings")
    .select("id, ticker, shares, cost_price, stocks(name)")
    .order("id");

  const tickers = [...new Set((holdings ?? []).map((h) => h.ticker))];
  // 全銘柄共通の件数上限だと、更新が止まった銘柄の行が他銘柄の履歴に押し出される。
  // 銘柄ごとに必要な2終値と最新指標だけを取得し、価格はsignalsより新しいpricesを使う。
  const quotes = await Promise.all(tickers.map(async (ticker) => {
    const [prices, signal] = await Promise.all([
      supabase.from("prices").select("date, close").eq("ticker", ticker)
        .not("close", "is", null).order("date", { ascending: false }).limit(2),
      supabase.from("signals").select("date, close, signal, rsi14").eq("ticker", ticker)
        .not("close", "is", null).order("date", { ascending: false }).limit(1).maybeSingle(),
    ]);
    return { ticker, prices, signal };
  }));
  const quoteErrors = [...new Set(quotes.flatMap((q) => [q.prices.error?.message, q.signal.error?.message]).filter(Boolean))];

  const latestByTicker = new Map<
    string,
    { close: number; date: string; signal: string | null; rsi14: number | null }
  >();
  const prevCloseByTicker = new Map<string, number>();
  for (const { ticker, prices, signal } of quotes) {
    const latest = prices.data?.[0] ?? signal.data;
    if (!latest || latest.close == null) continue;
    latestByTicker.set(ticker, {
      close: latest.close, date: latest.date,
      signal: signal.data?.signal ?? null, rsi14: signal.data?.rsi14 ?? null,
    });
    const prev = prices.data?.[1];
    if (prev?.close != null) prevCloseByTicker.set(ticker, prev.close);
  }

  const rows = (holdings ?? []).map((h) => {
    const stockName = Array.isArray(h.stocks) ? h.stocks[0]?.name : (h.stocks as { name: string } | null)?.name;
    const latest = latestByTicker.get(h.ticker);
    const currentPrice = latest?.close ?? null;
    const profitRate = currentPrice
      ? ((currentPrice - h.cost_price) / h.cost_price) * 100
      : null;
    const marketValue = currentPrice ? currentPrice * h.shares : null;
    const costValue = h.cost_price * h.shares;
    const profitAmount = marketValue != null ? marketValue - costValue : null;

    // 前日比（前営業日終値との比較）。取得単価とは無関係に「今日の値動き」を示す。
    const prevClose = prevCloseByTicker.get(h.ticker) ?? null;
    const dayChangeRate =
      currentPrice != null && prevClose ? ((currentPrice - prevClose) / prevClose) * 100 : null;
    const prevMarketValue = prevClose != null ? prevClose * h.shares : null;
    const dayChangeAmount =
      marketValue != null && prevMarketValue != null ? marketValue - prevMarketValue : null;

    // 推奨損切り価格（取得単価 -8%）。現在値が割っていれば到達フラグを立てる。
    const stopLossPrice = h.cost_price * (1 - STOP_LOSS_PCT);
    const stopLossHit = currentPrice != null && currentPrice <= stopLossPrice;

    return {
      ...h,
      stockName,
      currentPrice,
      currentPriceDate: latest?.date ?? null,
      profitRate,
      profitAmount,
      marketValue,
      prevMarketValue,
      costValue,
      dayChangeRate,
      dayChangeAmount,
      stopLossPrice,
      stopLossHit,
      signal: latest?.signal ?? null,
      risk: riskLevel(latest?.rsi14 ?? null, profitRate),
    };
  });

  const lossAlerts = rows.filter((r) => r.profitRate != null && r.profitRate <= LOSS_ALERT_THRESHOLD);
  const gainAlerts = rows.filter((r) => r.profitRate != null && r.profitRate >= GAIN_ALERT_THRESHOLD);

  const totalMarketValue = rows.reduce((sum, r) => sum + (r.marketValue ?? r.costValue), 0);
  const totalCostValue = rows.reduce((sum, r) => sum + r.costValue, 0);
  const totalProfit = totalMarketValue - totalCostValue;
  const totalProfitRate = totalCostValue ? (totalProfit / totalCostValue) * 100 : 0;

  // 前日比（ポートフォリオ全体）。前日終値が取れない銘柄は現在値をそのまま前日値として扱い
  // (変化なし扱い)、合計の整合性を保つ。
  const totalPrevMarketValue = rows.reduce(
    (sum, r) => sum + (r.prevMarketValue ?? r.marketValue ?? r.costValue),
    0
  );
  const totalDayChange = totalMarketValue - totalPrevMarketValue;
  const totalDayChangeRate = totalPrevMarketValue ? (totalDayChange / totalPrevMarketValue) * 100 : 0;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">ポートフォリオ</h1>
        <p className="text-sm text-muted-foreground mt-1">保有株の評価損益とリスクを確認</p>
      </div>

      {(lossAlerts.length > 0 || gainAlerts.length > 0) && (
        <div className="flex flex-col gap-2">
          {lossAlerts.map((h) => (
            <DismissibleAlert
              key={`loss-${h.id}`}
              id={`loss-${h.id}`}
              className="rounded-lg border border-bearish/30 bg-bearish/10 px-4 py-3 text-sm font-medium text-bearish"
            >
              <AlertTriangle className="size-4 shrink-0" />
              {h.stockName ?? h.ticker}が{Math.abs(h.profitRate ?? 0).toFixed(1)}%下落しています（損益アラート）
            </DismissibleAlert>
          ))}
          {gainAlerts.map((h) => (
            <DismissibleAlert
              key={`gain-${h.id}`}
              id={`gain-${h.id}`}
              className="rounded-lg border border-bullish/30 bg-bullish/10 px-4 py-3 text-sm font-medium text-bullish"
            >
              <AlertTriangle className="size-4 shrink-0" />
              {h.stockName ?? h.ticker}が{(h.profitRate ?? 0).toFixed(1)}%上昇しています（利益確定の検討を）
            </DismissibleAlert>
          ))}
        </div>
      )}

      {rows.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">評価額</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold tabular-nums">¥{Math.round(totalMarketValue).toLocaleString()}</p>
              {rows.some((r) => r.dayChangeAmount != null) && (
                <div
                  className={cn(
                    "flex items-center gap-0.5 text-xs font-medium tabular-nums mt-1",
                    totalDayChange >= 0 ? "text-bullish" : "text-bearish"
                  )}
                >
                  {totalDayChange >= 0 ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}
                  前日比 {totalDayChange >= 0 ? "+" : "-"}¥{Math.round(Math.abs(totalDayChange)).toLocaleString()}
                  <span>
                    ({totalDayChange >= 0 ? "+" : ""}
                    {totalDayChangeRate.toFixed(1)}%)
                  </span>
                </div>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">取得額</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold tabular-nums">¥{Math.round(totalCostValue).toLocaleString()}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">評価損益</CardTitle>
            </CardHeader>
            <CardContent>
              <div className={cn("flex items-center gap-1 text-2xl font-bold tabular-nums", totalProfit >= 0 ? "text-bullish" : "text-bearish")}>
                {totalProfit >= 0 ? <ArrowUpRight className="size-5" /> : <ArrowDownRight className="size-5" />}
                ¥{Math.round(Math.abs(totalProfit)).toLocaleString()}
                <span className="text-sm font-medium">
                  ({totalProfit >= 0 ? "+" : "-"}
                  {Math.abs(totalProfitRate).toFixed(1)}%)
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {rows.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">資産配分</CardTitle>
          </CardHeader>
          <CardContent>
            <AllocationChart
              data={rows.map((h) => ({
                name: h.stockName ?? h.ticker,
                value: h.marketValue ?? h.costValue,
              }))}
            />
          </CardContent>
        </Card>
      )}

      <HoldingsForm error={formError} collapsedByDefault={rows.length > 0} holdingsCount={rows.length} />

      {error && <p className="text-bearish text-sm">データ取得エラー: {error.message}</p>}
      {quoteErrors.length > 0 && (
        <p className="text-bearish text-sm">株価・指標取得エラー: {quoteErrors.join(" / ")}</p>
      )}
      {rows.some((r) => r.marketValue == null) && (
        <p className="text-sm text-muted-foreground">終値未取得の銘柄は、評価額と資産配分の合計に取得額を使用しています。</p>
      )}

      {!error && rows.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-12 text-center">
          <Wallet className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">保有株が登録されていません。上のフォームから追加してください。</p>
        </div>
      )}

      {success === "add" && (
        <div className="rounded-lg border border-bullish/30 bg-bullish/10 px-4 py-3 text-sm font-medium text-bullish">
          保有株を追加しました。
        </div>
      )}
      {success === "delete" && (
        <div className="rounded-lg border border-bullish/30 bg-bullish/10 px-4 py-3 text-sm font-medium text-bullish">
          保有株を削除しました。
        </div>
      )}

      <div className="flex flex-col gap-2">
        {rows.map((h) => (
          <div
            key={h.id}
            className="flex flex-col gap-3 rounded-xl border border-border bg-card px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <Link href={`/stock/${h.ticker}`} className="font-semibold hover:underline">
                {h.stockName ?? h.ticker}{" "}
                <span className="text-muted-foreground text-xs">{h.ticker}</span>
              </Link>
              <p className="text-sm text-muted-foreground mt-0.5">
                {h.shares}株 / 取得単価 ¥{h.cost_price.toLocaleString()}
                {h.currentPrice != null && (
                  <> / {h.currentPriceDate ? getCloseLabel(h.currentPriceDate) : "前日終値"} ¥{h.currentPrice.toLocaleString()}</>
                )}
                {h.dayChangeRate != null && h.dayChangeAmount != null && (
                  <span
                    className={cn(
                      "ml-1.5 inline-flex items-center gap-0.5 font-medium tabular-nums whitespace-nowrap",
                      h.dayChangeRate >= 0 ? "text-bullish" : "text-bearish"
                    )}
                  >
                    {h.dayChangeRate >= 0 ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}
                    前日比 {h.dayChangeAmount >= 0 ? "+" : "-"}¥{Math.round(Math.abs(h.dayChangeAmount)).toLocaleString()}
                    {" "}({h.dayChangeRate >= 0 ? "+" : ""}
                    {h.dayChangeRate.toFixed(1)}%)
                  </span>
                )}
              </p>
              <p
                className={cn(
                  "text-xs mt-0.5 tabular-nums",
                  h.stopLossHit ? "text-bearish font-medium" : "text-muted-foreground"
                )}
              >
                推奨損切り ¥{Math.round(h.stopLossPrice).toLocaleString()}（取得単価-8%）
                {h.stopLossHit && " ・到達"}
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 sm:flex-1 sm:justify-end">
              {h.marketValue != null && h.profitAmount != null && (
                <div className="flex flex-col items-end gap-0.5">
                  <span className="text-sm font-semibold tabular-nums">
                    ¥{Math.round(h.marketValue).toLocaleString()}
                  </span>
                  {h.profitRate != null && (
                    <span
                      className={cn(
                        "flex items-center gap-0.5 text-xs font-medium tabular-nums whitespace-nowrap",
                        h.profitRate >= 0 ? "text-bullish" : "text-bearish"
                      )}
                    >
                      {h.profitRate >= 0 ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}
                      {h.profitRate >= 0 ? "+" : ""}
                      {Math.round(h.profitAmount).toLocaleString()}円 ({h.profitRate >= 0 ? "+" : ""}
                      {h.profitRate.toFixed(1)}%)
                    </span>
                  )}
                </div>
              )}

              <div className="flex items-center gap-3 shrink-0">
                <Badge className={h.risk.className}>リスク{h.risk.label}</Badge>
                {h.signal === "sell_candidate" && (
                  <Badge className="bg-bearish text-bearish-foreground">売り時</Badge>
                )}
                <DeleteHoldingButton id={h.id} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
