import Link from "next/link";
import { fetchPerformance } from "@/lib/performance-data";
import {
  groupOutcomes,
  selectOutcomes,
  summarize,
} from "@/lib/performance-summary";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export default async function PerformancePage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const days = (await searchParams).days === "30" ? 30 : 90;
  const { rows, error } = await fetchPerformance();
  const selected = selectOutcomes(rows, days);
  const total = summarize(selected);
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">AI本番成績の分析</h1>
        <p className="text-sm text-muted-foreground mt-1">
          確定実績をスコア帯・業種・モデル世代ごとに比較
        </p>
      </div>
      <div className="flex gap-2">
        {[30, 90].map((value) => (
          <Link
            key={value}
            href={`/performance?days=${value}`}
            aria-current={days === value ? "page" : undefined}
            className={cn(
              "rounded-lg border px-4 py-2 text-sm",
              days === value && "bg-secondary font-semibold",
            )}
          >
            直近{value}日
          </Link>
        ))}
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        決済日が期間内にある確定実績を集計。翌営業日始値で約定し、8%損切りまたは5営業日後始値で決済した、業種/TOPIXに対する超過リターン（往復コスト0.2%控除後）です。勝率はこの値がプラスの割合で、株価自体の上昇率ではありません。スコアは相対順位で、上昇確率ではありません。
      </p>
      {error ? (
        <p role="alert" className="text-bearish">
          実績を取得できませんでした。時間をおいて再度お試しください。
        </p>
      ) : !total ? (
        <p className="text-muted-foreground">
          この期間の確定実績はありません。
        </p>
      ) : (
        <>
          <Card>
            <CardContent className="flex flex-wrap gap-6 text-sm">
              <span>確定 {total.trades}件</span>
              <span>勝率 {(total.winRate * 100).toFixed(1)}%</span>
              <span>
                平均ネット超過リターン {(total.netReturn * 100).toFixed(2)}%
              </span>
            </CardContent>
          </Card>
          <p className="text-xs text-muted-foreground">
            20件未満は「少数」と表示します。同日の候補は値動きが似るため、件数が多くても独立した検証とは限りません。モデル世代によって評価期間も異なります。
          </p>
          {(
            [
              ["score", "AI相対スコア帯別"],
              ["sector", "業種別"],
              ["model", "モデル世代別"],
            ] as const
          ).map(([by, title]) => (
            <Card key={by}>
              <CardHeader>
                <CardTitle className="text-base">{title}</CardTitle>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <div className="space-y-4 sm:hidden">
                  {groupOutcomes(selected, by).map((group) => (
                    <div
                      key={group.label}
                      className="border-b pb-3 last:border-0 last:pb-0"
                    >
                      <p className="text-sm font-medium break-all">
                        {group.label}
                      </p>
                      <dl className="grid grid-cols-3 gap-2 mt-2 text-xs">
                        <div>
                          <dt className="text-muted-foreground">件数</dt>
                          <dd className="mt-1 tabular-nums">
                            {group.trades}
                            {group.trades < 20 && "（少数）"}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">勝率</dt>
                          <dd className="mt-1 tabular-nums">
                            {(group.winRate * 100).toFixed(1)}%
                          </dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">
                            平均ネット超過
                          </dt>
                          <dd
                            className={cn(
                              "mt-1 tabular-nums",
                              group.netReturn >= 0
                                ? "text-bullish"
                                : "text-bearish",
                            )}
                          >
                            {group.netReturn >= 0 ? "+" : ""}
                            {(group.netReturn * 100).toFixed(2)}%
                          </dd>
                        </div>
                      </dl>
                    </div>
                  ))}
                </div>
                <table className="hidden sm:table w-full text-sm">
                  <thead>
                    <tr className="border-b text-muted-foreground">
                      <th scope="col" className="text-left p-2">
                        {by === "model"
                          ? "モデル世代"
                          : by === "sector"
                            ? "業種"
                            : "スコア帯"}
                      </th>
                      <th
                        scope="col"
                        className="text-right p-2 whitespace-nowrap"
                      >
                        件数
                      </th>
                      <th
                        scope="col"
                        className="text-right p-2 whitespace-nowrap"
                      >
                        勝率
                      </th>
                      <th
                        scope="col"
                        className="text-right p-2 whitespace-nowrap"
                      >
                        平均ネット超過
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupOutcomes(selected, by).map((group) => (
                      <tr key={group.label} className="border-b last:border-0">
                        <th
                          scope="row"
                          className="text-left p-2 font-normal break-all min-w-40"
                        >
                          {group.label}
                        </th>
                        <td className="text-right p-2 tabular-nums whitespace-nowrap">
                          {group.trades}
                          {group.trades < 20 && (
                            <span className="text-muted-foreground text-xs ml-1">
                              少数
                            </span>
                          )}
                        </td>
                        <td className="text-right p-2 tabular-nums">
                          {(group.winRate * 100).toFixed(1)}%
                        </td>
                        <td
                          className={cn(
                            "text-right p-2 tabular-nums",
                            group.netReturn >= 0
                              ? "text-bullish"
                              : "text-bearish",
                          )}
                        >
                          {group.netReturn >= 0 ? "+" : ""}
                          {(group.netReturn * 100).toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}
