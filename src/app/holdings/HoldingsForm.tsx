"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export default function HoldingsForm() {
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const [name, setName] = useState("");
  const [shares, setShares] = useState("");
  const [costPrice, setCostPrice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const trimmedTicker = ticker.trim();

    // 銘柄マスタになければ追加(name未入力ならtickerをそのまま表示名に)
    const { error: stockError } = await supabase
      .from("stocks")
      .upsert(
        { ticker: trimmedTicker, name: name.trim() || trimmedTicker },
        { onConflict: "ticker", ignoreDuplicates: true }
      );

    if (stockError) {
      setError(stockError.message);
      setSubmitting(false);
      return;
    }

    const { error: holdingError } = await supabase.from("holdings").insert({
      ticker: trimmedTicker,
      shares: Number(shares),
      cost_price: Number(costPrice),
    });

    if (holdingError) {
      setError(holdingError.message);
      setSubmitting(false);
      return;
    }

    setTicker("");
    setName("");
    setShares("");
    setCostPrice("");
    setSubmitting(false);
    router.refresh();
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-4"
    >
      <h2 className="font-semibold text-sm">保有株を追加</h2>

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-sm">
          ティッカー
          <input
            required
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="例: 7203.T"
            className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-base text-zinc-100"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          銘柄名（任意）
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例: トヨタ自動車"
            className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-base text-zinc-100"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          株数
          <input
            required
            type="number"
            min="0"
            step="any"
            value={shares}
            onChange={(e) => setShares(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-base text-zinc-100"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          取得単価（円）
          <input
            required
            type="number"
            min="0"
            step="any"
            value={costPrice}
            onChange={(e) => setCostPrice(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-base text-zinc-100"
          />
        </label>
      </div>

      {error && <p className="text-red-400 text-sm">エラー: {error}</p>}

      <button
        type="submit"
        disabled={submitting}
        className="self-start rounded bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
      >
        {submitting ? "追加中..." : "追加"}
      </button>
    </form>
  );
}
