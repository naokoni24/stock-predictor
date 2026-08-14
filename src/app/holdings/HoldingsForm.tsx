"use client";

import { useState } from "react";
import { ChevronDown, PlusCircle } from "lucide-react";
import { addHolding } from "./actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import TickerSearch from "./TickerSearch";
import { SubmitButton } from "@/components/login-submit-button";
import { cn } from "@/lib/utils";

export default function HoldingsForm({ error, collapsedByDefault }: { error?: string; collapsedByDefault?: boolean }) {
  const [open, setOpen] = useState(!collapsedByDefault);

  return (
    <Card className="border-primary/40 shadow-sm">
      <CardHeader
        className={cn("bg-primary/5 rounded-t-xl", collapsedByDefault && "cursor-pointer")}
        onClick={collapsedByDefault ? () => setOpen((v) => !v) : undefined}
      >
        <CardTitle className="text-base flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-primary">
            <PlusCircle className="size-4" />
            保有株を追加
          </span>
          {collapsedByDefault && (
            <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
          )}
        </CardTitle>
      </CardHeader>
      {open && (
      <CardContent>
        <form
          action={addHolding}
          onSubmit={(e) => {
            const formData = new FormData(e.currentTarget);
            if (!String(formData.get("ticker") ?? "").trim()) {
              e.preventDefault();
              alert("銘柄候補の一覧から銘柄を選択してください。");
              return;
            }
            if (!confirm("この内容で保有株を追加しますか？")) {
              e.preventDefault();
            }
          }}
          className="flex flex-col gap-4"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <TickerSearch />
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="shares">株数</Label>
              <Input
                id="shares"
                name="shares"
                required
                type="number"
                min="0.0001"
                step="any"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="costPrice">取得単価（円）</Label>
              <Input
                id="costPrice"
                name="costPrice"
                required
                type="number"
                min="0.0001"
                step="any"
              />
            </div>
          </div>

          {error && (
            <div className="rounded-lg border border-bearish/30 bg-bearish/10 px-4 py-3 text-sm font-medium text-bearish">
              エラー: {error}
            </div>
          )}

          <SubmitButton label="追加" pendingLabel="登録中..." />
        </form>
      </CardContent>
      )}
    </Card>
  );
}
