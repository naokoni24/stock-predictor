import Link from "next/link";
import { ArrowDownRight, ArrowUpRight, Wallet } from "lucide-react";
import { supabase } from "@/lib/supabase";
import HoldingsForm from "./HoldingsForm";
import DeleteHoldingButton from "./DeleteHoldingButton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

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

export default async function HoldingsPage() {
  const { data: holdings, error } = await supabase
    .from("holdings")
    .select("id, ticker, shares, cost_price, stocks(name)")
    .order("id");

  const tickers = (holdings ?? []).map((h) => h.ticker);

  const { data: latestSignals } = tickers.length
    ? await supabase
        .from("signals")
        .select("ticker, date, close, signal, rsi14")
        .in("ticker", tickers)
        .order("date", { ascending: false })
    : { data: [] };

  // 各銘柄の最新シグナルのみ残す
  const latestByTicker = new Map<
    string,
    { close: number; signal: string | null; rsi14: number | null }
  >();
  for (const s of latestSignals ?? []) {
    if (!latestByTicker.has(s.ticker)) {
      latestByTicker.set(s.ticker, { close: s.close, signal: s.signal, rsi14: s.rsi14 });
    }
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

    return {
      ...h,
      stockName,
      currentPrice,
      profitRate,
      profitAmount,
      marketValue,
      costValue,
      signal: latest?.signal ?? null,
      risk: riskLevel(latest?.rsi14 ?? null, profitRate),
    };
  });

  const totalMarketValue = rows.reduce((sum, r) => sum + (r.marketValue ?? r.costValue), 0);
  const totalCostValue = rows.reduce((sum, r) => sum + r.costValue, 0);
  const totalProfit = totalMarketValue - totalCostValue;
  const totalProfitRate = totalCostValue ? (totalProfit / totalCostValue) * 100 : 0;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">ポートフォリオ</h1>
        <p className="text-sm text-muted-foreground mt-1">保有株の評価損益とリスクを確認</p>
      </div>

      {rows.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">評価額</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold tabular-nums">¥{Math.round(totalMarketValue).toLocaleString()}</p>
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

      <HoldingsForm />

      {error && <p className="text-bearish text-sm">データ取得エラー: {error.message}</p>}

      {!error && rows.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-12 text-center">
          <Wallet className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">保有株が登録されていません。上のフォームから追加してください。</p>
        </div>
      )}

      <div className="flex flex-col gap-2">
        {rows.map((h) => (
          <div
            key={h.id}
            className="flex items-center justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3.5"
          >
            <div className="min-w-0">
              <Link href={`/stock/${h.ticker}`} className="font-semibold hover:underline">
                {h.stockName ?? h.ticker}{" "}
                <span className="text-muted-foreground text-xs">{h.ticker}</span>
              </Link>
              <p className="text-sm text-muted-foreground mt-0.5">
                {h.shares}株 / 取得単価 ¥{h.cost_price.toLocaleString()}
                {h.currentPrice != null && <> / 現在値 ¥{h.currentPrice.toLocaleString()}</>}
              </p>
            </div>

            <div className="flex items-center gap-3 shrink-0">
              {h.profitRate != null && (
                <span
                  className={cn(
                    "flex items-center gap-0.5 text-sm font-semibold tabular-nums",
                    h.profitRate >= 0 ? "text-bullish" : "text-bearish"
                  )}
                >
                  {h.profitRate >= 0 ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
                  {h.profitRate >= 0 ? "+" : ""}
                  {h.profitRate.toFixed(1)}%
                </span>
              )}
              <Badge className={h.risk.className}>リスク{h.risk.label}</Badge>
              {h.signal === "sell_candidate" && (
                <Badge className="bg-bearish text-bearish-foreground">売り時</Badge>
              )}
              <DeleteHoldingButton id={h.id} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
