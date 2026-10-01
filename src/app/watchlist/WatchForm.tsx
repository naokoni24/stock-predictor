"use client";
import TickerSearch from "@/app/holdings/TickerSearch";
import { SubmitButton } from "@/components/login-submit-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { addWatch, updateWatch } from "./actions";

export default function WatchForm({
  ticker,
  above,
  below,
  signalAlert = true,
}: {
  ticker?: string;
  above?: number | null;
  below?: number | null;
  signalAlert?: boolean;
}) {
  const suffix = ticker ?? "new";
  return (
    <form
      action={ticker ? updateWatch : addWatch}
      className="space-y-3"
      onSubmit={(e) => {
        if (!String(new FormData(e.currentTarget).get("ticker") ?? "").trim()) {
          e.preventDefault();
          alert("銘柄を候補から選択してください。");
        }
      }}
    >
      {ticker ? (
        <input name="ticker" type="hidden" value={ticker} />
      ) : (
        <TickerSearch allowManual={false} />
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor={`above-${suffix}`}>上限価格（円・任意）</Label>
          <Input
            id={`above-${suffix}`}
            name="priceAbove"
            type="number"
            step="any"
            min="0.0001"
            max="1000000000000"
            defaultValue={above ?? ""}
            placeholder="この価格以上で表示"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`below-${suffix}`}>下限価格（円・任意）</Label>
          <Input
            id={`below-${suffix}`}
            name="priceBelow"
            type="number"
            step="any"
            min="0.0001"
            max="1000000000000"
            defaultValue={below ?? ""}
            placeholder="この価格以下で表示"
          />
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          name="signalAlert"
          defaultChecked={signalAlert}
        />
        シグナル変化を知らせる
      </label>
      <SubmitButton
        label={ticker ? "条件を保存" : "ウォッチリストに追加"}
        pendingLabel="保存中..."
      />
    </form>
  );
}
