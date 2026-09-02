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
import { cn, getCloseLabel } from "@/lib/utils";

const SIGNAL_LABEL: Record<string, string> = {
  buy_candidate: "買い候補",
  sell_candidate: "売り候補",
  hold: "様子見",
};

// 推奨損切り幅（エントリー=現在値からの下落率）。バックテストで-8%が好成績だったため。
const STOP_LOSS_PCT = 0.08;

type Row = {
  ticker: string;
  date: string;
  close: number | null;
  rsi14: number | null;
  signal: string | null;
  score: number | null;
  ml_signal: string | null;
  ml_score: number | null;
  ml_threshold: number | null;
  ml_block_reasons: string[] | null;
  stockName?: string;
  sector?: string;
  changePct?: number | null;
};

type OutcomeRow = {
  outcome_date: string;
  net_return: number;
  model_version: string;
  evaluation_version: string | null;
};

function isMissingMlExplanationColumn(error: { message?: string | null; code?: string | null } | null) {
  const message = error?.message ?? "";
  return error?.code === "PGRST204" || message.includes("ml_threshold") || message.includes("ml_block_reasons");
}

async function fetchWatchlists() {
  const initialResult = await supabase
    .from("signals")
    .select("ticker, date, close, rsi14, signal, score, ml_signal, ml_score, ml_threshold, ml_block_reasons, stocks(name, sector)")
    .order("date", { ascending: false })
    .limit(800);
  let signals = initialResult.data;
  let error = initialResult.error;

  // SQL適用前の一時的な旧スキーマでも、既存のウォッチリスト表示を止めない。
  if (isMissingMlExplanationColumn(error)) {
    const legacyResult = await supabase
      .from("signals")
      .select("ticker, date, close, rsi14, signal, score, ml_signal, ml_score, stocks(name, sector)")
      .order("date", { ascending: false })
      .limit(800);
    signals = legacyResult.data?.map((row) => ({
      ...row,
      ml_threshold: null,
      ml_block_reasons: null,
    })) ?? null;
    error = legacyResult.error;
  }

  // 銘柄ごとに最新日のシグナルのみを残す(買い/売り候補どちらのタブでも同じ最新日を使う)。
  // yfinanceが当日終値をまだ確定配信していない日はclose/signalがnullで保存されるため、
  // そのような行はスキップして直近の有効な行を使う。
  const latestByTicker = new Map<string, NonNullable<typeof signals>[number]>();
  for (const s of signals ?? []) {
    if (!latestByTicker.has(s.ticker) && s.close != null) {
      latestByTicker.set(s.ticker, s);
    }
  }
  const latest = Array.from(latestByTicker.values());

  const buildRows = (signalType: "buy_candidate" | "sell_candidate"): Row[] =>
    latest
      .filter((s) => s.signal === signalType)
      .sort((a, b) =>
        signalType === "sell_candidate"
          ? (a.score ?? 0) - (b.score ?? 0)
          : (b.score ?? 0) - (a.score ?? 0)
      )
      .slice(0, 10)
      .map((s) => {
        const stock = Array.isArray(s.stocks) ? s.stocks[0] : s.stocks;
        return {
          ...s,
          stockName: stock?.name,
          sector: stock?.sector,
        };
      });

  const buyRows = buildRows("buy_candidate");
  const sellRows = buildRows("sell_candidate");

  const tickers = [...new Set([...buyRows, ...sellRows].map((r) => r.ticker))];
  if (tickers.length) {
    const since = new Date();
    since.setDate(since.getDate() - 10);
    const { data: prices } = await supabase
      .from("prices")
      .select("ticker, date, close")
      .in("ticker", tickers)
      .gte("date", since.toISOString().slice(0, 10))
      .order("date", { ascending: false });

    // yfinanceが当日終値をまだ確定配信していない日/取引低調日はcloseがnullで
    // 保存されるため、そのような行をスキップしないと前日比が(null - 実値)で
    // 誤って-100%近い値として計算されてしまう不具合があった。直近の有効な2件のみを使う。
    const byTicker = new Map<string, number[]>();
    for (const p of prices ?? []) {
      if (p.close == null) continue;
      const arr = byTicker.get(p.ticker) ?? [];
      if (arr.length < 2) arr.push(p.close);
      byTicker.set(p.ticker, arr);
    }
    for (const r of [...buyRows, ...sellRows]) {
      const arr = byTicker.get(r.ticker);
      if (arr && arr.length === 2 && arr[1]) {
        r.changePct = ((arr[0] - arr[1]) / arr[1]) * 100;
      }
    }
  }

  return {
    buy: { rows: buyRows, error },
    sell: { rows: sellRows, error },
  };
}

function isMissingOutcomeTable(error: { message?: string | null; code?: string | null } | null) {
  const message = error?.message ?? "";
  return error?.code === "PGRST205" || message.includes("signal_outcomes") || message.includes("evaluation_version");
}

function summarizeOutcomes(rows: OutcomeRow[], days: number) {
  const since = new Date();
  since.setDate(since.getDate() - days);
  const sinceDate = since.toISOString().slice(0, 10);
  const selected = rows.filter((row) => row.outcome_date >= sinceDate);
  if (selected.length === 0) return null;
  const netReturn = selected.reduce((sum, row) => sum + row.net_return, 0) / selected.length;
  return {
    trades: selected.length,
    winRate: selected.filter((row) => row.net_return > 0).length / selected.length,
    netReturn,
  };
}

async function fetchLivePerformance() {
  const { data, error } = await supabase
    .from("signal_outcomes")
    .select("outcome_date, net_return, model_version, evaluation_version")
    .order("outcome_date", { ascending: false })
    .limit(500);
  if (isMissingOutcomeTable(error)) return { recent: null, longer: null, latestModel: null, error: null };
  // 旧定義(終値ベースの絶対リターン)を新定義の超過リターンへ混ぜない。
  const rows = ((data ?? []) as OutcomeRow[]).filter(
    (row) => row.evaluation_version === "next_open_stop_excess_v1"
  );
  return {
    recent: summarizeOutcomes(rows, 30),
    longer: summarizeOutcomes(rows, 90),
    latestModel: rows[0]?.model_version ?? null,
    error,
  };
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

function AiScoreBar({ score, threshold }: { score: number | null | undefined; threshold?: number | null }) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const isEligible = threshold == null || score >= threshold;
  return (
    <div className="flex items-center gap-2 w-full max-w-48">
      <div className="h-1.5 flex-1 rounded-full bg-secondary overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full",
            isEligible ? "bg-bullish" : "bg-bearish"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-medium tabular-nums text-muted-foreground w-9 text-right">
        {pct}
      </span>
    </div>
  );
}

function aiScoreLabel(score: number): string {
  if (score < 0.2) return "非常に弱気";
  if (score < 0.35) return "弱気";
  if (score < 0.45) return "やや弱気";
  if (score < 0.55) return "様子見";
  return "やや強気";
}

function WatchlistRow({ s, signalType }: { s: Row; signalType: string }) {
  return (
    <Link
      href={`/stock/${s.ticker}`}
      className="flex items-center justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3.5 transition-colors hover:bg-accent/50"
    >
      <div className="flex flex-col gap-0.5 min-w-0 flex-1 max-w-xs">
        <div className="flex items-center gap-2">
          <p className="font-semibold text-sm sm:text-lg truncate">{s.stockName ?? s.ticker}</p>
          <span className="text-muted-foreground text-xs shrink-0">{s.ticker}</span>
        </div>
        <p className="text-xs text-muted-foreground truncate">
          {s.sector ?? "ー"} · RSI {s.rsi14?.toFixed(1) ?? "ー"}
        </p>
        {signalType === "buy_candidate" && s.ml_score != null && (
          s.ml_signal === "buy_candidate" ? (
            <span className="text-[10px] text-bullish">
              ※AI相対スコアも買い条件を満たしています
            </span>
          ) : (
            <span
              className={cn(
                "text-[10px]",
                s.ml_score < 0.45 ? "text-bearish" : "text-muted-foreground"
              )}
            >
              ※AI相対スコアは{aiScoreLabel(s.ml_score)}です
            </span>
          )
        )}
        {signalType === "buy_candidate" && s.close != null && (
          <span className="text-[10px] text-muted-foreground tabular-nums">
            推奨損切り ¥{Math.round(s.close * (1 - STOP_LOSS_PCT)).toLocaleString()}（-8%）
          </span>
        )}
      </div>

      {signalType === "buy_candidate" && (
        <div className="hidden sm:flex flex-1 items-center justify-center self-center">
          <AiScoreBar score={s.ml_score} threshold={s.ml_threshold} />
        </div>
      )}

      <div className="flex flex-col items-end gap-1.5 shrink-0">
        <div className="flex items-end gap-3">
          <div className="flex flex-col items-end gap-0.5">
            <span className="text-[10px] text-muted-foreground">{getCloseLabel(s.date)}</span>
            <span className="font-semibold tabular-nums">
              {s.close != null ? `¥${s.close.toLocaleString()}` : "ー"}
            </span>
          </div>
          <ChangeBadge value={s.changePct} />
        </div>
        <div className="flex items-center justify-center gap-2 w-full">
          {s.signal === "buy_candidate" && s.ml_signal === "buy_candidate" ? (
            <Badge className="bg-bullish text-bullish-foreground">本命</Badge>
          ) : s.ml_signal === "buy_candidate" ? (
            <Badge variant="secondary">AI買い</Badge>
          ) : (
            <Badge variant="outline">{SIGNAL_LABEL[s.signal ?? ""] ?? "ー"}</Badge>
          )}
          {signalType === "buy_candidate" && (
            <div className="sm:hidden">
              <AiScoreBar score={s.ml_score} threshold={s.ml_threshold} />
            </div>
          )}
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
  const [{ buy, sell }, news, performance] = await Promise.all([
    fetchWatchlists(),
    fetchNews(),
    fetchLivePerformance(),
  ]);

  const topPick = buy.rows[0];

  const latestDate = [...buy.rows, ...sell.rows]
    .map((r) => r.date)
    .sort()
    .at(-1);

  // 日次バッチの実行時刻は過去に13:00 JST→15:30 JSTへ変更されており、GitHub Actionsの
  // スケジュール遅延(実績30〜40分程度)もあるため、固定の時刻表記(旧: 16:30時点)は
  // バッチ時刻変更のたびにずれる。実際の実行時刻に依存しない「日付+取引終了後」表記にする。
  const lastUpdatedLabel = latestDate
    ? `最終更新: ${new Date(`${latestDate}T00:00:00+09:00`).toLocaleDateString("ja-JP", {
        timeZone: "Asia/Tokyo",
        month: "long",
        day: "numeric",
      })} 取引終了後時点`
    : null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">本日のおすすめ</h1>
        <p className="text-sm text-muted-foreground mt-1">
          AIモデルとテクニカル指標に基づく売買候補ウォッチリスト
        </p>
        {lastUpdatedLabel && (
          <p className="text-xs text-muted-foreground mt-1">{lastUpdatedLabel}</p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <Tabs defaultValue="buy" className="flex-col gap-3">
            <TabsList>
              <TabsTrigger
                value="buy"
                className="gap-1.5 data-[state=active]:bg-bullish data-[state=active]:text-bullish-foreground data-[state=active]:font-semibold dark:data-[state=active]:bg-bullish dark:data-[state=active]:text-bullish-foreground"
              >
                <ArrowUpRight className="size-4" />
                買い候補
              </TabsTrigger>
              <TabsTrigger
                value="sell"
                className="gap-1.5 data-[state=active]:bg-bearish data-[state=active]:text-bearish-foreground data-[state=active]:font-semibold dark:data-[state=active]:bg-bearish dark:data-[state=active]:text-bearish-foreground"
              >
                <ArrowDownRight className="size-4" />
                売り候補
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
                    <span className="text-sm text-muted-foreground">AI相対スコア</span>
                    {topPick.ml_score != null ? (
                      <span className="font-semibold tabular-nums text-bullish">
                        {(topPick.ml_score * 100).toFixed(0)}
                      </span>
                    ) : (
                      <span className="text-sm text-muted-foreground">ー</span>
                    )}
                  </div>
                  {topPick.ml_threshold != null && (
                    <p className="text-xs text-muted-foreground -mt-2">
                      買いしきい値 {Math.round(topPick.ml_threshold * 100)}
                    </p>
                  )}

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
                    {" AI相対スコアは確率ではなく、同モデル内での相対的な強さです。"}
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
                <Sparkles className="size-4 text-chart-2" />
                AI本番成績
              </CardTitle>
            </CardHeader>
            <CardContent>
              {performance.error && (
                <p className="text-bearish text-sm">データ取得エラー: {performance.error.message}</p>
              )}
              {!performance.error && !performance.recent && (
                <p className="text-sm leading-relaxed text-muted-foreground">
                  AI買い候補を5営業日後に評価します。最初の成績は5営業日後から表示されます。
                </p>
              )}
              {performance.recent && (
                <div className="flex flex-col gap-3">
                  <PerformanceRow label="直近30日" stats={performance.recent} />
                  {performance.longer && <PerformanceRow label="直近90日" stats={performance.longer} />}
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    翌営業日始値で約定し、8%損切りまたは5営業日後始値で決済。業種/TOPIXに対する超過リターンから往復コスト0.2%を控除した参考値です。
                  </p>
                  {performance.latestModel && (
                    <p className="text-[10px] text-muted-foreground break-all">
                      モデル世代: {performance.latestModel}
                    </p>
                  )}
                </div>
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

function PerformanceRow({
  label,
  stats,
}: {
  label: string;
  stats: { trades: number; winRate: number; netReturn: number };
}) {
  const positive = stats.netReturn >= 0;
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label} ({stats.trades}件)</span>
      <div className="flex items-center gap-3 text-right tabular-nums">
        <span>勝率 {(stats.winRate * 100).toFixed(0)}%</span>
        <span className={cn("font-semibold", positive ? "text-bullish" : "text-bearish")}>
          平均 {positive ? "+" : ""}{(stats.netReturn * 100).toFixed(2)}%
        </span>
      </div>
    </div>
  );
}
