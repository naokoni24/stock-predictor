"use client";

import { useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

const SIGNAL_LABEL: Record<string, string> = {
  buy_candidate: "買い候補",
  sell_candidate: "売り候補",
  hold: "様子見",
};

type StockRow = {
  ticker: string;
  name: string | null;
  sector: string | null;
  signal: string | null;
};

export default function SearchableStockList({ stocks }: { stocks: StockRow[] }) {
  const [query, setQuery] = useState("");

  const q = query.trim().toLowerCase();
  const filtered = q
    ? stocks.filter(
        (s) =>
          s.ticker.toLowerCase().includes(q) ||
          (s.name ?? "").toLowerCase().includes(q) ||
          (s.sector ?? "").toLowerCase().includes(q)
      )
    : stocks;

  return (
    <div className="flex flex-col gap-4">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="銘柄名・コード・業種で検索"
          className="pl-9"
        />
      </div>

      {filtered.length === 0 && (
        <p className="text-muted-foreground text-sm">該当する銘柄がありません。</p>
      )}

      <div className="flex flex-col gap-2">
        {filtered.map((s) => (
          <Link
            key={s.ticker}
            href={`/stock/${s.ticker}`}
            className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3.5 transition-colors hover:bg-accent/50"
          >
            <div className="min-w-0">
              <p className="font-semibold truncate">
                {s.name ?? s.ticker}{" "}
                <span className="text-muted-foreground text-xs">{s.ticker}</span>
              </p>
              {s.sector && <p className="text-xs text-muted-foreground mt-0.5">{s.sector}</p>}
            </div>
            {s.signal && (
              <Badge
                variant={s.signal === "hold" ? "outline" : "default"}
                className={
                  s.signal === "buy_candidate"
                    ? "bg-bullish text-bullish-foreground"
                    : s.signal === "sell_candidate"
                      ? "bg-bearish text-bearish-foreground"
                      : ""
                }
              >
                {SIGNAL_LABEL[s.signal] ?? "ー"}
              </Badge>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
