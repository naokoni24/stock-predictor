import Link from "next/link";
import { fetchMarketSignals } from "@/lib/activity-data";
import { signalChanges, validPrice } from "@/lib/signal-activity";
import { createClient } from "@/lib/supabase-server";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export async function SignalChanges({
  compact = false,
}: {
  compact?: boolean;
}) {
  const supabase = await createClient();
  const [market, holdings] = await Promise.all([
    fetchMarketSignals(),
    supabase.from("holdings").select("ticker"),
  ]);
  const owned = new Set((holdings.data ?? []).map((row) => row.ticker));
  const changes = signalChanges(market.current, market.previous).sort(
    (a, b) =>
      Number(owned.has(b.ticker)) - Number(owned.has(a.ticker)) ||
      a.ticker.localeCompare(b.ticker),
  );
  const previousTickers = new Set(
    market.previous.filter((r) => validPrice(r.close)).map((r) => r.ticker),
  );
  const compared = market.current.filter(
    (r) => validPrice(r.close) && previousTickers.has(r.ticker),
  ).length;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          前回更新からのシグナル変化{" "}
          <span className="text-muted-foreground">{changes.length}件</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {market.error ? (
          <p role="alert" className="text-bearish text-sm">
            シグナルを取得できませんでした。
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {market.previousDate && market.latestDate
                ? `${market.previousDate} → ${market.latestDate}・比較可能 ${compared}銘柄`
                : "比較には2回分の更新が必要です。"}
            </p>
            {!compact && (
              <p className="text-xs text-muted-foreground">
                両日に終値がある銘柄を比較します。分析対象の入れ替わり・価格欠損は変化として数えません。
              </p>
            )}
            {holdings.error && (
              <p className="text-xs text-bearish">
                保有株の識別を取得できませんでした。
              </p>
            )}
            {market.previousDate && !changes.length && (
              <p className="text-sm text-muted-foreground">
                比較できる銘柄にシグナル変化はありません。
              </p>
            )}
            {(compact ? changes.slice(0, 5) : changes).map((row) => (
              <Link
                key={row.ticker}
                href={`/stock/${row.ticker}`}
                className="block rounded-lg border p-3 hover:bg-accent/50 space-y-1"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-sm">
                    {row.name ?? row.ticker}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {row.ticker}
                  </span>
                  {owned.has(row.ticker) && (
                    <Badge variant="secondary">保有中</Badge>
                  )}
                </div>
                {row.changes.map((change) => (
                  <p key={change} className="text-sm">
                    {change}
                  </p>
                ))}
                {row.scoreDelta != null && (
                  <p className="text-xs text-muted-foreground">
                    AI相対スコア差 {row.scoreDelta >= 0 ? "+" : ""}
                    {row.scoreDelta.toFixed(2)}
                  </p>
                )}
                {row.modelChanged && (
                  <p className="text-xs text-muted-foreground">
                    モデル世代が変わりました
                  </p>
                )}
              </Link>
            ))}
          </>
        )}
        {compact && (
          <Link
            href="/changes"
            className="inline-block text-sm text-primary underline"
          >
            変化一覧をすべて見る
          </Link>
        )}
      </CardContent>
    </Card>
  );
}
