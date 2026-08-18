"use client";

import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type StockOption = { ticker: string; name: string };

// ユーザーは "7267" のように証券コードだけ入力することが多いため、
// 拡張子(.T など)が付いていなければ東証の ".T" を補う。
function normalizeManualTicker(raw: string): string {
  const trimmed = raw.trim().toUpperCase();
  if (!trimmed) return "";
  return /\.[A-Z]+$/.test(trimmed) ? trimmed : `${trimmed}.T`;
}

export default function TickerSearch() {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<StockOption[]>([]);
  const [selected, setSelected] = useState<StockOption | null>(null);
  const [open, setOpen] = useState(false);
  const [manualMode, setManualMode] = useState(false);
  const [manualTicker, setManualTicker] = useState("");
  const [manualName, setManualName] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (selected || query.trim().length < 1) {
      return;
    }

    const timer = setTimeout(async () => {
      // 銘柄名だけでなく証券コードでも検索できるようにする
      // (「本田技研工業」のようにカタカナの通称では名前検索にヒットしない銘柄があるため)。
      // .or()に検索語をそのまま埋め込むと、PostgRESTのor構文はカンマを条件の区切り文字
      // として解釈するため、検索語に「,」が含まれると400エラーになり候補が出せなくなる
      // (かつエラーを読んでいなかったため無反応に見えていた)。name/tickerを別クエリに
      // 分けて実行しmerge・重複除去することでこの問題を避ける。
      const [byName, byTicker] = await Promise.all([
        supabase.from("stocks").select("ticker, name").ilike("name", `%${query}%`).limit(8),
        supabase.from("stocks").select("ticker, name").ilike("ticker", `%${query}%`).limit(8),
      ]);

      if (byName.error) console.error("stock search (name) failed:", byName.error.message);
      if (byTicker.error) console.error("stock search (ticker) failed:", byTicker.error.message);

      const merged = new Map<string, StockOption>();
      for (const row of [...(byName.data ?? []), ...(byTicker.data ?? [])]) {
        merged.set(row.ticker, row);
      }
      setOptions(Array.from(merged.values()).slice(0, 8));
    }, 250);

    return () => clearTimeout(timer);
  }, [query, selected]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const visibleOptions = selected || query.trim().length < 1 ? [] : options;

  // 候補をクリックせずEnterで送信すると、ticker未選択のまま
  // フォームが送信され「ティッカーを入力してください」の紛らわしいエラーになるため、
  // Enterは常にフォーム送信を止め、候補があれば先頭候補を選択したことにする。
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (!selected && visibleOptions.length > 0) {
      setSelected(visibleOptions[0]);
      setOptions([]);
      setOpen(false);
    }
  };

  const manualTickerNormalized = normalizeManualTicker(manualTicker);
  const manualReady = manualTickerNormalized.length > 0 && manualName.trim().length > 0;
  const effectiveTicker = manualMode
    ? (manualReady ? manualTickerNormalized : "")
    : (selected?.ticker ?? "");
  const effectiveName = manualMode
    ? (manualReady ? manualName.trim() : "")
    : (selected?.name ?? "");

  if (manualMode) {
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="manual-ticker">証券コードで直接追加</Label>
        <div className="grid grid-cols-2 gap-2">
          <Input
            id="manual-ticker"
            value={manualTicker}
            onChange={(e) => setManualTicker(e.target.value)}
            placeholder="例: 2201 または 2201.T"
          />
          <Input
            id="manual-name"
            value={manualName}
            onChange={(e) => setManualName(e.target.value)}
            placeholder="銘柄名(例: 森永製菓)"
          />
        </div>
        <button
          type="button"
          className="self-start text-xs text-muted-foreground underline hover:text-foreground"
          onClick={() => {
            setManualMode(false);
            setManualTicker("");
            setManualName("");
          }}
        >
          銘柄名で検索する
        </button>
        <input type="hidden" name="ticker" value={effectiveTicker} />
        <input type="hidden" name="name" value={effectiveName} />
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex flex-col gap-1.5 relative">
      <Label htmlFor="stock-search">銘柄名・証券コードで検索</Label>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          id="stock-search"
          value={selected ? `${selected.name} (${selected.ticker})` : query}
          onChange={(e) => {
            setSelected(null);
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="例: トヨタ / 7203"
          className="pl-8"
          autoComplete="off"
        />
      </div>
      {!selected && (
        <p className="text-xs text-muted-foreground">
          候補一覧から銘柄をクリックして選択してください
        </p>
      )}

      {open && visibleOptions.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 z-10 rounded-lg border border-border bg-popover shadow-md max-h-56 overflow-y-auto">
          {visibleOptions.map((o) => (
            <button
              key={o.ticker}
              type="button"
              className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-sm text-left hover:bg-accent"
              onClick={() => {
                setSelected(o);
                setOptions([]);
                setOpen(false);
              }}
            >
              <span>{o.name}</span>
              <span className="text-xs text-muted-foreground">{o.ticker}</span>
            </button>
          ))}
        </div>
      )}

      <button
        type="button"
        className="self-start text-xs text-muted-foreground underline hover:text-foreground"
        onClick={() => {
          setManualMode(true);
          setSelected(null);
          setQuery("");
          setOptions([]);
          setOpen(false);
        }}
      >
        見つからない場合は証券コードで直接追加
      </button>

      <input type="hidden" name="ticker" value={effectiveTicker} />
      <input type="hidden" name="name" value={effectiveName} />
    </div>
  );
}
