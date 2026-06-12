"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const STORAGE_PREFIX = "dismissedAlert:";

// 日本時間の日付文字列(YYYY-MM-DD)を取得
function todayJst(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo" }).format(new Date());
}

export default function DismissibleAlert({
  id,
  className,
  children,
}: {
  id: string;
  className?: string;
  children: React.ReactNode;
}) {
  const [closed, setClosed] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const storedDate = localStorage.getItem(`${STORAGE_PREFIX}${id}`);
    if (storedDate === todayJst() && ref.current) {
      ref.current.style.display = "none";
    }
  }, [id]);

  if (closed) return null;

  return (
    <div ref={ref} className={cn("flex items-center gap-2 pr-2", className)}>
      <div className="flex-1 flex items-center gap-2">{children}</div>
      <button
        type="button"
        aria-label="閉じる"
        onClick={() => {
          localStorage.setItem(`${STORAGE_PREFIX}${id}`, todayJst());
          setClosed(true);
        }}
        className="shrink-0 rounded-md p-1 hover:bg-black/5 dark:hover:bg-white/10"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}
