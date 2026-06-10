import { addHolding } from "./actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export default function HoldingsForm({ error }: { error?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">保有株を追加</CardTitle>
      </CardHeader>
      <CardContent>
        <form action={addHolding} className="flex flex-col gap-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ticker">ティッカー</Label>
              <Input
                id="ticker"
                name="ticker"
                required
                placeholder="例: 7203.T"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="name">銘柄名（任意）</Label>
              <Input
                id="name"
                name="name"
                placeholder="例: トヨタ自動車"
              />
            </div>
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

          {error && <p className="text-bearish text-sm">エラー: {error}</p>}

          <Button type="submit" className="self-start">
            追加
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
