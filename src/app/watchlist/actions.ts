"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase-server";
import { parseWatchPrices } from "@/lib/signal-activity";

function fail(message: string): never {
  redirect(`/watchlist?error=${encodeURIComponent(message)}`);
}
function storageError(error: { code?: string; message: string }): never {
  if (error.code === "PGRST205" || error.code === "42P01")
    fail("ウォッチリストの初期設定が必要です。SQLを適用してください。");
  if (error.code === "23505")
    fail("この銘柄は登録済みです。下の一覧から条件を変更できます。");
  if (error.code === "23514")
    fail("登録上限（30銘柄）または価格条件を確認してください。");
  console.error("ウォッチリスト保存エラー:", error.message);
  fail("保存できませんでした。時間をおいて再度お試しください。");
}
async function authenticatedClient() {
  const supabase = await createClient();
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();
  if (!user || error) redirect("/login");
  return { supabase, user };
}
function tickerValue(form: FormData) {
  const ticker = String(form.get("ticker") ?? "")
    .trim()
    .toUpperCase();
  if (!/^[0-9A-Z]{4}\.T$/.test(ticker))
    fail("日本株の銘柄を候補から選択してください。");
  return ticker;
}
function ruleValues(form: FormData) {
  const prices = parseWatchPrices(
    String(form.get("priceAbove") ?? ""),
    String(form.get("priceBelow") ?? ""),
  );
  if (prices.error) fail(prices.error);
  return {
    price_above: prices.price_above,
    price_below: prices.price_below,
    signal_alert: form.get("signalAlert") === "on",
  };
}
function done(message: string): never {
  revalidatePath("/watchlist");
  redirect(`/watchlist?success=${encodeURIComponent(message)}`);
}
export async function addWatch(form: FormData) {
  const ticker = tickerValue(form),
    rules = ruleValues(form);
  const { supabase, user } = await authenticatedClient();
  const stock = await supabase
    .from("stocks")
    .select("ticker")
    .eq("ticker", ticker)
    .maybeSingle();
  if (stock.error || !stock.data)
    fail("登録銘柄一覧にある銘柄を選択してください。");
  const { error } = await supabase
    .from("watchlists")
    .insert({ user_id: user.id, ticker, ...rules });
  if (error) storageError(error);
  done("ウォッチリストに追加しました。");
}
export async function updateWatch(form: FormData) {
  const ticker = tickerValue(form),
    rules = ruleValues(form);
  const { supabase, user } = await authenticatedClient();
  const { data, error } = await supabase
    .from("watchlists")
    .update(rules)
    .eq("user_id", user.id)
    .eq("ticker", ticker)
    .select("ticker");
  if (error) storageError(error);
  if (!data?.length) fail("登録が見つかりません。再読み込みしてください。");
  done("アラート条件を保存しました。");
}
export async function deleteWatch(form: FormData) {
  const ticker = tickerValue(form);
  const { supabase, user } = await authenticatedClient();
  const { error } = await supabase
    .from("watchlists")
    .delete()
    .eq("user_id", user.id)
    .eq("ticker", ticker);
  if (error) storageError(error);
  done("ウォッチリストから削除しました。");
}
