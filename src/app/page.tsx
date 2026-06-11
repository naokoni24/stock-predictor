import Link from "next/link";
import { ArrowDownRight, ArrowUpRight, Newspaper, Sparkles } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const SIGNAL_LABEL: Record<string, string> = {
  buy_candidate: "買い候補",
  sell_candidate: "売り候補",
  hold: "様子見",
};

type Row = {
  ticker: string;
  date: string;
  close: number | null;
  rsi14: number | null;
  signal: string | null;
  score: number | null;
  ml_signal: string | null;
  ml_score: number | null;
  stockName?: string;
  sector?: string;
  changePct?: number | null;
};

async function fetchTab(signalType: "buy_candidate" | "sell_candidate") {
  const { data: signals, error } = await supabase
    .from("signals")
    .select("ticker, date, close, rsi14, signal, score, ml_signal, ml_score, stocks(name, sector)")
    .eq("signal", signalType)
    .order("date", { ascending: false })
    .order("score", { ascending: signalType === "sell_candidate" });

  // 銘柄ごとに最新日のシグナルのみを残す
  const latestByTicker = new Map<string, NonNullable<typeof signals>[number]>();
  for (const s of signals ?? []) {
    if (!latestByTicker.has(s.ticker)) {
      latestByTicker.set(s.ticker, s);
    }
  }

  const rows: Row[] = Array.from(latestByTicker.values())
    .slice(0, 10)
    .map((s) => {
      const stock = Array.isArray(s.stocks) ? s.stocks[0] : s.stocks;
      return {
        ...s,
        stockName: stock?.name,
        sector: stock?.sector,
      };
    });

  const tickers = rows.map((r) => r.ticker);
  if (tickers.length) {
    const { data: prices } = await supabase
      .from("prices")
      .select("ticker, date, close")
      .in("ticker", tickers)
      .order("date", { ascending: false });

    const byTicker = new Map<string, number[]>();
    for (const p of prices ?? []) {
      const arr = byTicker.get(p.ticker) ?? [];
      if (arr.length < 2) arr.push(p.close);
      byTicker.set(p.ticker, arr);
    }
    for (const r of rows) {
      const arr = byTicker.get(r.ticker);
      if (arr && arr.length === 2 && arr[1]) {
        r.changePct = ((arr[0] - arr[1]) / arr[1]) * 100;
      }
    }
  }

  return { rows, error };
}

function ChangeBadge({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-muted-foreground text-xs">ー</span>;
  const positive = value >= 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-sm font-medium tabular-nums",
        positive ? "text-bullish" : "text-bearish"
      )}
    >
      {positive ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
      {positive ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}

function AiScoreBar({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  return (
    <div className="flex items-center gap-2 w-full max-w-28">
      <div className="h-1.5 flex-1 rounded-full bg-secondary overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full",
            pct >= 50 ? "bg-bullish" : "bg-bearish"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-medium tabular-nums text-muted-foreground w-9 text-right">
        {pct}%
      </span>
    </div>
  );
}

function WatchlistRow({ s, signalType }: { s: Row; signalType: string }) {
  return (
    <Link
      href={`/stock/${s.ticker}`}
      className="flex items-center justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3.5 transition-colors hover:bg-accent/50"
    >
      <div className="flex flex-col gap-0.5 min-w-0">
        <div className="flex items-center gap-2">
          <p className="font-semibold truncate">{s.stockName ?? s.ticker}</p>
          <span className="text-muted-foreground text-xs shrink-0">{s.ticker}</span>
        </div>
        <p className="text-xs text-muted-foreground truncate">
          {s.sector ?? "ー"} · RSI {s.rsi14?.toFixed(1) ?? "ー"}
        </p>
      </div>

      <div className="flex flex-col items-end gap-1.5 shrink-0">
        <div className="flex items-center gap-3">
          <span className="font-semibold tabular-nums">
            {s.close != null ? `¥${s.close.toLocaleString()}` : "ー"}
          </span>
          <ChangeBadge value={s.changePct} />
        </div>
        <div className="flex items-center gap-2">
          {s.signal === "buy_candidate" && s.ml_signal === "buy_candidate" ? (
            <Badge className="bg-bullish text-bullish-foreground">本命</Badge>
          ) : s.ml_signal === "buy_candidate" ? (
            <Badge variant="secondary">AI買い</Badge>
          ) : (
            <Badge variant="outline">{SIGNAL_LABEL[s.signal ?? ""] ?? "ー"}</Badge>
          )}
          {signalType === "buy_candidate" && <AiScoreBar score={s.ml_score} />}
        </div>
      </div>
    </Link>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-12 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

async function fetchNews() {
  const { data, error } = await supabase
    .from("news")
    .select("ticker, title, url, source, published_at, sentiment, stocks(name)")
    .order("published_at", { ascending: false })
    .limit(6);

  const rows = (data ?? []).map((n) => {
    const stock = Array.isArray(n.stocks) ? n.stocks[0] : n.stocks;
    return { ...n, stockName: stock?.name };
  });

  return { rows, error };
}

const SENTIMENT_LABEL: Record<string, string> = {
  positive: "ポジティブ",
  negative: "ネガティブ",
  neutral: "中立",
};

const SENTIMENT_COLOR: Record<string, string> = {
  positive: "bg-bullish text-bullish-foreground",
  negative: "bg-bearish text-bearish-foreground",
  neutral: "bg-secondary text-secondary-foreground",
};

export default async function Home() {
  const [buy, sell, news] = await Promise.all([
    fetchTab("buy_candidate"),
    fetchTab("sell_candidate"),
    fetchNews(),
  ]);

  const topPick = buy.rows[0];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">本日のおすすめ</h1>
        <p className="text-sm text-muted-foreground mt-1">
          AIモデルとテクニカル指標に基づく売買候補ウォッチリスト
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <Tabs defaultValue="buy" className="flex-col gap-3">
            <TabsList>
              <TabsTrigger value="buy" className="gap-1.5 data-[state=active]:text-bullish">
                <ArrowUpRight className="size-4" />
                買い候補
                <Badge variant="secondary" className="ml-1">{buy.rows.length}</Badge>
              </TabsTrigger>
              <TabsTrigger value="sell" className="gap-1.5 data-[state=active]:text-bearish">
                <ArrowDownRight className="size-4" />
                売り候補
                <Badge variant="secondary" className="ml-1">{sell.rows.length}</Badge>
              </TabsTrigger>
            </TabsList>

            <TabsContent value="buy" className="flex flex-col gap-2 mt-3">
              {buy.error && (
                <p className="text-bearish text-sm">データ取得エラー: {buy.error.message}</p>
              )}
              {!buy.error && buy.rows.length === 0 && (
                <EmptyState message="本日の買い候補はありません。" />
              )}
              {buy.rows.map((s) => (
                <WatchlistRow key={s.ticker} s={s} signalType="buy_candidate" />
              ))}
            </TabsContent>

            <TabsContent value="sell" className="flex flex-col gap-2 mt-3">
              {sell.error && (
                <p className="text-bearish text-sm">データ取得エラー: {sell.error.message}</p>
              )}
              {!sell.error && sell.rows.length === 0 && (
                <EmptyState message="本日の売り候補はありません。" />
              )}
              {sell.rows.map((s) => (
                <WatchlistRow key={s.ticker} s={s} signalType="sell_candidate" />
              ))}
            </TabsContent>
          </Tabs>
        </div>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Sparkles className="size-4 text-bullish" />
                AI注目銘柄
              </CardTitle>
            </CardHeader>
            <CardContent>
              {topPick ? (
                <div className="flex flex-col gap-3">
                  <div>
                    <p className="font-semibold text-lg">
                      {topPick.stockName ?? topPick.ticker}
                    </p>
                    <p className="text-xs text-muted-foreground">{topPick.ticker} · {topPick.sector ?? "ー"}</p>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">AI上昇期待度</span>
                    {topPick.ml_score != null ? (
                      <span className="font-semibold tabular-nums text-bullish">
                        {(topPick.ml_score * 100).toFixed(0)}%
                      </span>
                    ) : (
                      <span className="text-sm text-muted-foreground">ー</span>
                    )}
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">テクニカルスコア</span>
                    <span className="font-semibold tabular-nums">{topPick.score ?? "ー"}</span>
                  </div>

                  <div className="rounded-lg bg-secondary p-3 text-xs leading-relaxed text-muted-foreground">
                    {topPick.ml_signal === "buy_candidate" && topPick.signal === "buy_candidate"
                      ? "テクニカル指標とAIモデルの両方が上昇を示唆しており、本命の買い候補です。"
                      : "テクニカル指標に基づき買い候補として検出されています。"}
                    {" "}
                    RSI {topPick.rsi14?.toFixed(1) ?? "ー"}。
                  </div>

                  <Link
                    href={`/stock/${topPick.ticker}`}
                    className="text-sm font-medium text-foreground hover:underline"
                  >
                    詳細を見る →
                  </Link>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">対象データがありません。</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Newspaper className="size-4" />
                マーケットニュース
              </CardTitle>
            </CardHeader>
            <CardContent>
              {news.error && (
                <p className="text-bearish text-sm">データ取得エラー: {news.error.message}</p>
              )}
              {!news.error && news.rows.length === 0 && (
                <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
                  <p className="text-sm text-muted-foreground">
                    ニュースはまだありません。次回の自動更新をお待ちください。
                  </p>
                </div>
              )}
              <div className="flex flex-col gap-3">
                {news.rows.map((n) => (
                  <a
                    key={n.url}
                    href={n.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex flex-col gap-1 rounded-lg p-2 -mx-2 transition-colors hover:bg-accent/50"
                  >
                    <p className="text-sm font-medium leading-snug line-clamp-2">{n.title}</p>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {n.stockName && <span>{n.stockName}</span>}
                      {n.source && <span>· {n.source}</span>}
                      {n.sentiment && (
                        <Badge className={cn("ml-auto", SENTIMENT_COLOR[n.sentiment])}>
                          {SENTIMENT_LABEL[n.sentiment] ?? n.sentiment}
                        </Badge>
                      )}
                    </div>
                  </a>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
