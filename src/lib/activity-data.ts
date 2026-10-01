import { cache } from "react";
import { supabase } from "@/lib/supabase";
import { type DailySignal } from "@/lib/signal-activity";

export const fetchMarketSignals = cache(async () => {
  const latest = await supabase
    .from("signals")
    .select("date")
    .not("close", "is", null)
    .order("date", { ascending: false })
    .limit(1)
    .maybeSingle();
  const latestDate: string | null = latest.data?.date ?? null;
  if (latest.error || !latestDate)
    return {
      latestDate,
      previousDate: null,
      current: [] as DailySignal[],
      previous: [] as DailySignal[],
      error: latest.error?.message ?? null,
    };
  const prev = await supabase
    .from("signals")
    .select("date")
    .not("close", "is", null)
    .lt("date", latestDate)
    .order("date", { ascending: false })
    .limit(1)
    .maybeSingle();
  const previousDate: string | null = prev.data?.date ?? null;
  async function load(date: string | null) {
    const rows: DailySignal[] = [];
    if (!date) return { rows, error: null };
    for (let offset = 0; ; offset += 1000) {
      const { data, error } = await supabase
        .from("signals")
        .select(
          "ticker, date, close, signal, ml_signal, ml_score, model_version, stocks(name)",
        )
        .eq("date", date)
        .order("ticker")
        .range(offset, offset + 999);
      if (error) return { rows: [] as DailySignal[], error: error.message };
      rows.push(
        ...(data ?? []).map((row) => ({
          ...row,
          name: (Array.isArray(row.stocks) ? row.stocks[0] : row.stocks)?.name,
        })),
      );
      if (!data || data.length < 1000) return { rows, error: null };
    }
  }
  const [current, previous] = await Promise.all([
    load(latestDate),
    load(previousDate),
  ]);
  return {
    latestDate,
    previousDate,
    current: current.rows,
    previous: previous.rows,
    error: prev.error?.message ?? current.error ?? previous.error,
  };
});
