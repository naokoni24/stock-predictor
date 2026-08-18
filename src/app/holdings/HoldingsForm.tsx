"use client";

import { useEffect, useState } from "react";
import { ChevronDown, PlusCircle } from "lucide-react";
import { addHolding } from "./actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import TickerSearch from "./TickerSearch";
import { SubmitButton } from "@/components/login-submit-button";
import { cn } from "@/lib/utils";

export default function HoldingsForm({
  error,
  collapsedByDefault,
  holdingsCount,
}: {
  error?: string;
  collapsedByDefault?: boolean;
  holdingsCount?: number;
}) {
  const [open, setOpen] = useState(!collapsedByDefault);

  // 保有株の有無（＝折りたたみ表示にすべきか）はサーバー側の再レンダリングで
  // props経由で変わるが、このコンポーネント自体はNextのソフトナビゲーションで
  // アンマウントされずuseStateの初期値も再評価されないため、保有株を全て削除した
  // 直後などcollapsedByDefaultの値が変化したタイミングでopen状態を明示的に
  // 同期する。これをしないと「保有株ゼロになりフォームは常時展開されるはず」の
  // 状態で、削除前の折りたたみ状態(open=false)が残ったままヘッダーのクリック
  // ハンドラも外れ(collapsedByDefault=falseのため)、追加ボタンを押しても
  // フォームが表示されない不具合になる。
  useEffect(() => {
    setOpen(!collapsedByDefault);
  }, [collapsedByDefault]);

  return (
    <Card className="border-2 border-primary shadow-md py-0 gap-0 overflow-hidden">
      <CardHeader
        className={cn(
          "bg-primary text-primary-foreground py-4",
          collapsedByDefault && "cursor-pointer"
        )}
        onClick={collapsedByDefault ? () => setOpen((v) => !v) : undefined}
      >
        <CardTitle className="text-lg flex items-center justify-between gap-2">
          <span className="flex items-center gap-2.5">
            <PlusCircle className="size-6" />
            保有株を追加
          </span>
          {collapsedByDefault && (
            <ChevronDown className={cn("size-5 transition-transform", open && "rotate-180")} />
          )}
        </CardTitle>
      </CardHeader>
      {open && (
      <CardContent className="pt-4 pb-4">
        <form
          // 保有株の追加・削除のたびにholdingsCountが変わるためkeyにする。
          // HoldingsFormはNextのソフトナビゲーションでアンマウントされないため、
          // keyを変えないと追加成功後もTickerSearchの選択銘柄・株数・取得単価の
          // 入力値が残ったままになり、連続追加時に誤って同じ銘柄を二重登録しやすい。
          key={holdingsCount}
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
                defaultValue={100}
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
