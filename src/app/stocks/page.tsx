import { supabase } from "@/lib/supabase";
import SearchableStockList from "./SearchableStockList";

const STOCKS_PAGE_SIZE = 1000;

type StockRow = { ticker: string; name: string; sector: string | null };

async function fetchAllStocks(): Promise<{ stocks: StockRow[]; error: string | null }> {
  const stocks: StockRow[] = [];
  let from = 0;

  while (true) {
    const { data, error } = await supabase
      .from("stocks")
      .select("ticker, name, sector")
      .order("ticker")
      .range(from, from + STOCKS_PAGE_SIZE - 1);

    if (error) {
      return { stocks, error: error.message };
    }

    stocks.push(...(data ?? []));

    if (!data || data.length < STOCKS_PAGE_SIZE) {
      break;
    }
    from += STOCKS_PAGE_SIZE;
  }

  return { stocks, error: null };
}

export default async function StocksPage() {
  const { stocks, error } = await fetchAllStocks();

  // シグナルは最新の市場日に分析した銘柄だけ表示する。以前は直近600件から銘柄ごとの
  // 最新行を集めており、分析対象から外れた銘柄の数日前のシグナルが日付表示なしに
  // 現在の判定のように出ていた(トップページで2026-09-26に修正した問題と同じ)。
  const { data: latestDateRow, error: latestDateError } = await supabase
    .from("signals")
    .select("date")
    .not("close", "is", null)
    .order("date", { ascending: false })
    .limit(1)
    .maybeSingle();
  const latestSignalResult = latestDateRow?.date
    ? await supabase
        .from("signals")
        .select("ticker, date, signal")
        .eq("date", latestDateRow.date)
        .not("close", "is", null)
        .limit(1000)
    : { data: [], error: null };
  const signals = latestSignalResult.data;
  const signalsError = latestDateError ?? latestSignalResult.error;

  const latestSignalByTicker = new Map<string, string | null>();
  for (const s of signals ?? []) {
    if (!latestSignalByTicker.has(s.ticker)) {
      latestSignalByTicker.set(s.ticker, s.signal);
    }
  }

  const rows = stocks.map((s) => ({
    ...s,
    signal: latestSignalByTicker.get(s.ticker) ?? null,
  }));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">登録銘柄一覧</h1>
        <p className="text-sm text-muted-foreground mt-1">
          監視対象銘柄を検索して詳細を確認(全{rows.length}銘柄)
          {latestDateRow?.date && `・シグナルは${latestDateRow.date}に分析した銘柄のみ表示`}
        </p>
      </div>

      {error && <p className="text-bearish text-sm">データ取得エラー: {error}</p>}
      {signalsError && (
        <p className="text-bearish text-sm">
          シグナル取得エラー: {signalsError.message}(銘柄一覧は表示されますが、シグナル表示が欠けている可能性があります)
        </p>
      )}

      {!error && rows.length === 0 && (
        <p className="text-muted-foreground text-sm">登録銘柄がありません。</p>
      )}

      {!error && rows.length > 0 && <SearchableStockList stocks={rows} />}
    </div>
  );
}
