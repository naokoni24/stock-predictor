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

  // 銘柄マスタになければ追加(name未入力ならtickerをそのまま表示名に)
  const { error: stockError } = await supabase
    .from("stocks")
    .upsert(
      { ticker, name: name || ticker },
      { onConflict: "ticker", ignoreDuplicates: true }
    );

  if (stockError) {
    redirectWithError(stockError.message);
  }

  const { error: holdingError } = await supabase.from("holdings").insert({
    ticker,
    shares,
    cost_price: costPrice,
  });

  if (holdingError) {
    redirectWithError(holdingError.message);
  }

  revalidatePath("/holdings");
  redirect("/holdings");
}

export async function deleteHolding(id: number) {
  const supabase = await createClient();
  const { error } = await supabase.from("holdings").delete().eq("id", id);

  if (error) {
    redirectWithError(error.message);
  }

  revalidatePath("/holdings");
}
