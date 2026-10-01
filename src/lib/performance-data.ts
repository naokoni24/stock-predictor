import { cache } from "react";
import { supabase } from "@/lib/supabase";
import {
  dateDaysAgo,
  EVALUATION_VERSION,
  selectOutcomes,
  summarize,
  type Outcome,
} from "@/lib/performance-summary";

export const fetchPerformance = cache(async () => {
  const rows: Outcome[] = [];
  const now = new Date();
  for (let offset = 0; ; offset += 1000) {
    const { data, error } = await supabase
      .from("signal_outcomes")
      .select(
        "ticker, signal_date, outcome_date, net_return, ml_score, model_version, sector, evaluation_version",
      )
      .eq("evaluation_version", EVALUATION_VERSION)
      .gte("outcome_date", dateDaysAgo(90, now))
      .lte("outcome_date", dateDaysAgo(0, now))
      .order("outcome_date", { ascending: false })
      .order("signal_date", { ascending: false })
      .order("ticker")
      .range(offset, offset + 999);
    if (error) return { rows: [] as Outcome[], error: error.message };
    rows.push(...((data ?? []) as Outcome[]));
    if (!data || data.length < 1000) break;
  }
  return { rows: selectOutcomes(rows, 90, now), error: null };
});
export async function fetchLivePerformance() {
  const { rows, error } = await fetchPerformance();
  return {
    recent: summarize(selectOutcomes(rows, 30)),
    longer: summarize(rows),
    latestModel: rows[0]?.model_version ?? null,
    error: error ? { message: error } : null,
  };
}
