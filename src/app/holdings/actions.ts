"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase-server";

function redirectWithError(message: string): never {
  redirect(`/holdings?error=${encodeURIComponent(message)}`);
}

export async function addHolding(formData: FormData) {
  const ticker = String(formData.get("ticker") ?? "").trim().toUpperCase();
  const name = String(formData.get("name") ?? "").trim();
  const shares = Number(formData.get("shares"));
  const costPrice = Number(formData.get("costPrice"));

  if (!ticker) {
    redirectWithError("ティッカーを入力してください。");
  }

  if (!Number.isFinite(shares) || shares <= 0) {
    redirectWithError("株数は0より大きい数値で入力してください。");
  }

  if (!Number.isFinite(costPrice) || costPrice <= 0) {
    redirectWithError("取得単価は0より大きい数値で入力してください。");
  }

  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirectWithError("ログインが必要です。");
  }

  // 銘柄マスタに存在しない場合のみ追加を試みる。
  // holdings.ticker は stocks(ticker) への外部キーのため、ここでの登録に
  // 失敗すると直後のholdings insertが必ず失敗する(FK違反)。RLS未設定などで
  // 挿入が拒否された場合は、分かりにくいFKエラーではなくここで案内する。
  const { data: existingStock } = await supabase
    .from("stocks")
    .select("ticker")
    .eq("ticker", ticker)
    .maybeSingle();

  if (!existingStock) {
    const { error: stockError } = await supabase
      .from("stocks")
      .insert({ ticker, name: name || ticker });

    if (stockError) {
      if (stockError.code === "42501") {
        redirectWithError(
          "この銘柄はまだ日次更新の対象になっていないため追加できません。翌営業日の更新後に再度お試しください。"
        );
      }
      redirectWithError(stockError.message);
    }
  }

  const { error: holdingError } = await supabase.from("holdings").insert({
    ticker,
    shares,
    cost_price: costPrice,
    user_id: user.id,
  });

  if (holdingError) {
    redirectWithError(holdingError.message);
  }

  revalidatePath("/holdings");
  redirect("/holdings?success=add");
}

export async function deleteHolding(id: number) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirectWithError("ログインが必要です。");
  }

  const { error } = await supabase
    .from("holdings")
    .delete()
    .eq("id", id)
    .eq("user_id", user.id);

  if (error) {
    redirectWithError(error.message);
  }

  revalidatePath("/holdings");
  redirect("/holdings?success=delete");
}
