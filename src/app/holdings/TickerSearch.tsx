"use client";

import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type StockOption = { ticker: string; name: string };

export default function TickerSearch() {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<StockOption[]>([]);
  const [selected, setSelected] = useState<StockOption | null>(null);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (selected || query.trim().length < 1) {
      return;
    }

    const timer = setTimeout(async () => {
      const { data } = await supabase
        .from("stocks")
        .select("ticker, name")
        .ilike("name", `%${query}%`)
        .limit(8);

      setOptions(data ?? []);
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

  return (
    <div ref={containerRef} className="flex flex-col gap-1.5 relative">
      <Label htmlFor="stock-search">銘柄名で検索</Label>
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
          placeholder="例: トヨタ"
          className="pl-8"
          autoComplete="off"
        />
      </div>

      {open && visibleOptions.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 z-10 rounded-lg border border-border bg-popover shadow-md max-h-56 overflow-y-auto">
          {visibleOptions.map((o) => (
            <button
              key={o.ticker}
              type="button"
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-sm text-left hover:bg-accent"
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

      <input type="hidden" name="ticker" value={selected?.ticker ?? ""} />
      <input type="hidden" name="name" value={selected?.name ?? ""} />
    </div>
  );
}
