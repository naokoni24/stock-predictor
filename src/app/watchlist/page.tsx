import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase-server";
import { fetchMarketSignals } from "@/lib/activity-data";
import { watchAlerts, validPrice, type WatchRule } from "@/lib/signal-activity";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import WatchForm from "./WatchForm";
import { deleteWatch } from "./actions";

export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; success?: string }>;
}) {
  const params = await searchParams;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const [result, market] = await Promise.all([
    supabase
      .from("watchlists")
      .select(
        "ticker, price_above, price_below, signal_alert, created_at, stocks(name)",
      )
      .eq("user_id", user.id)
      .order("created_at")
      .order("ticker"),
    fetchMarketSignals(),
  ]);
  const missing =
    result.error?.code === "PGRST205" || result.error?.code === "42P01";
  const entries = await Promise.all(
    (result.data ?? []).map(async (row) => {
      const quote = await supabase
        .from("prices")
        .select("date, close")
        .eq("ticker", row.ticker)
        .not("close", "is", null)
        .order("date", { ascending: false })
        .limit(1)
        .maybeSingle();
      const current =
        market.current.find((s) => s.ticker === row.ticker) ?? null;
      const previous =
        market.previous.find((s) => s.ticker === row.ticker) ?? null;
      const price =
        quote.data ??
        (current ? { date: current.date, close: current.close } : null);
      const alerts =
        market.error || quote.error
          ? []
          : watchAlerts(
              row as WatchRule,
              price,
              current,
              previous,
              market.latestDate,
            );
      const fresh =
        !market.error &&
        !quote.error &&
        validPrice(price?.close) &&
        price?.date === market.latestDate &&
        current?.date === market.latestDate;
      return {
        ...row,
        price,
        alerts,
        fresh,
        quoteError: quote.error,
        name: (Array.isArray(row.stocks) ? row.stocks[0] : row.stocks)?.name,
      };
    }),
  );
  const alertCount = entries.filter((row) => row.alerts.length > 0).length;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">個人ウォッチリスト</h1>
        <p className="text-sm text-muted-foreground mt-1">
          気になる銘柄とアラート条件を保存（1人30銘柄まで）
        </p>
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        日次更新後、最新市場日の終値が上限以上・下限以下ならアラートを表示します。シグナルは直近2回の更新を比較し、登録前の変化は知らせません。アプリを開いて確認する方式です。分析対象の上限に達した銘柄は更新待ちになります。
      </p>
      {params.error && (
        <p role="alert" className="text-sm text-bearish">
          {params.error}
        </p>
      )}
      {params.success && (
        <p role="status" className="text-sm text-bullish">
          {params.success}
        </p>
      )}
      {missing ? (
        <Card>
          <CardContent className="text-sm space-y-2">
            <p>ウォッチリストの初期設定が必要です。</p>
            <p>
              Supabase SQL Editorで{" "}
              <code>supabase/add_personal_watchlists.sql</code>{" "}
              を実行してください。
            </p>
          </CardContent>
        </Card>
      ) : result.error ? (
        <p role="alert" className="text-bearish">
          ウォッチリストを取得できませんでした。
        </p>
      ) : (
        <>
          {market.error && (
            <p role="alert" className="text-bearish text-sm">
              最新シグナルを取得できないため、アラートの判定を停止しています。
            </p>
          )}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                銘柄を追加 {entries.length}/30
              </CardTitle>
            </CardHeader>
            <CardContent>
              {entries.length < 30 ? (
                <WatchForm key={entries.map((e) => e.ticker).join(",")} />
              ) : (
                <p className="text-sm text-muted-foreground">
                  追加するには登録済みの銘柄を削除してください。
                </p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                現在のアラート {alertCount}銘柄
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {!alertCount && (
                <p className="text-sm text-muted-foreground">
                  現在、条件に該当する銘柄はありません。
                </p>
              )}
              {entries
                .filter((e) => e.alerts.length)
                .map((e) => (
                  <Link
                    href={`/stock/${e.ticker}`}
                    key={e.ticker}
                    className="block rounded-lg border border-primary/30 p-3"
                  >
                    <p className="font-medium text-sm">
                      {e.name ?? e.ticker}{" "}
                      <span className="text-xs text-muted-foreground">
                        {e.price?.date}
                      </span>
                    </p>
                    {e.alerts.map((alert) => (
                      <p key={alert} className="text-sm mt-1">
                        {alert}
                      </p>
                    ))}
                  </Link>
                ))}
            </CardContent>
          </Card>
          {!entries.length && (
            <p className="text-sm text-muted-foreground">
              ウォッチリストはまだ空です。
            </p>
          )}
          {entries.map((e) => (
            <Card key={e.ticker}>
              <CardHeader>
                <div className="flex justify-between gap-3">
                  <Link
                    href={`/stock/${e.ticker}`}
                    className="font-semibold hover:underline"
                  >
                    {e.name ?? e.ticker}{" "}
                    <span className="text-muted-foreground text-xs">
                      {e.ticker}
                    </span>
                  </Link>
                  <form action={deleteWatch}>
                    <input type="hidden" name="ticker" value={e.ticker} />
                    <Button
                      type="submit"
                      size="sm"
                      variant="outline"
                      aria-label={`${e.name ?? e.ticker}をウォッチリストから削除`}
                    >
                      削除
                    </Button>
                  </form>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2 items-center text-sm">
                  <span>
                    {e.price?.close != null
                      ? `終値 ¥${e.price.close.toLocaleString()}（${e.price.date}）`
                      : "終値未取得"}
                  </span>
                  {!e.fresh && <Badge variant="secondary">更新待ち</Badge>}
                </div>
                {e.quoteError && (
                  <p className="text-xs text-bearish">
                    価格の取得に失敗しました。
                  </p>
                )}
                <details>
                  <summary className="cursor-pointer text-sm text-primary">
                    アラート条件を変更
                  </summary>
                  <div className="pt-3">
                    <WatchForm
                      key={`${e.price_above}-${e.price_below}-${e.signal_alert}`}
                      ticker={e.ticker}
                      above={e.price_above}
                      below={e.price_below}
                      signalAlert={e.signal_alert}
                    />
                  </div>
                </details>
              </CardContent>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}
