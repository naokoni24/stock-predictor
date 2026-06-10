"use client";

import { useState } from "react";
import Link from "next/link";

const SIGNAL_LABEL: Record<string, string> = {
  buy_candidate: "買い候補",
  sell_candidate: "売り候補",
  hold: "様子見",
};

const SIGNAL_COLOR: Record<string, string> = {
  buy_candidate: "bg-green-100 text-green-800",
  sell_candidate: "bg-red-100 text-red-800",
  hold: "bg-zinc-100 text-zinc-700",
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
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="銘柄名・コード・業種で検索"
        className="w-full rounded-lg border px-3 py-2 text-sm"
      />

      {filtered.length === 0 && (
        <p className="text-zinc-500 text-sm">該当する銘柄がありません。</p>
      )}

      <div className="flex flex-col gap-2">
        {filtered.map((s) => (
          <Link
            key={s.ticker}
            href={`/stock/${s.ticker}`}
            className="flex items-center justify-between rounded-lg border bg-white px-4 py-3 hover:bg-zinc-50"
          >
            <div>
              <p className="font-semibold">
                {s.name ?? s.ticker}{" "}
                <span className="text-zinc-400 text-xs">{s.ticker}</span>
              </p>
              {s.sector && <p className="text-xs text-zinc-500">{s.sector}</p>}
            </div>
            {s.signal && (
              <span
                className={`text-xs font-semibold px-2 py-1 rounded-full ${
                  SIGNAL_COLOR[s.signal] ?? "bg-zinc-100 text-zinc-700"
                }`}
              >
                {SIGNAL_LABEL[s.signal] ?? "ー"}
              </span>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
