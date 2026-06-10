"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">保有株を追加</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ticker">ティッカー</Label>
              <Input
                id="ticker"
                required
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="例: 7203.T"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="name">銘柄名（任意）</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例: トヨタ自動車"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="shares">株数</Label>
              <Input
                id="shares"
                required
                type="number"
                min="0"
                step="any"
                value={shares}
                onChange={(e) => setShares(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="costPrice">取得単価（円）</Label>
              <Input
                id="costPrice"
                required
                type="number"
                min="0"
                step="any"
                value={costPrice}
                onChange={(e) => setCostPrice(e.target.value)}
              />
            </div>
          </div>

          {error && <p className="text-bearish text-sm">エラー: {error}</p>}

          <Button type="submit" disabled={submitting} className="self-start">
            {submitting ? "追加中..." : "追加"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
