"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Wallet, ListFilter, LineChart } from "lucide-react";

import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "本日のおすすめ", icon: LayoutDashboard },
  { href: "/holdings", label: "ポートフォリオ", icon: Wallet },
  { href: "/stocks", label: "登録銘柄一覧", icon: ListFilter },
];

export function SiteSidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex md:w-60 md:flex-col md:border-r md:border-border md:py-6 md:px-4 md:gap-1">
      <div className="flex items-center gap-2 px-2 pb-6">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <LineChart className="size-4" />
        </div>
        <span className="font-semibold tracking-tight">StockSense AI</span>
      </div>

      {NAV_ITEMS.map((item) => {
        const active =
          item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
            )}
          >
            <Icon className="size-4" />
            {item.label}
          </Link>
        );
      })}
    </aside>
  );
}
