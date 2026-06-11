"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Wallet, ListFilter, LineChart, LogOut } from "lucide-react";

import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

const NAV_ITEMS = [
  { href: "/", label: "おすすめ", icon: LayoutDashboard },
  { href: "/holdings", label: "ポートフォリオ", icon: Wallet },
  { href: "/stocks", label: "銘柄一覧", icon: ListFilter },
];

export function SiteHeader({
  isLoggedIn,
  onLogout,
}: {
  isLoggedIn: boolean;
  onLogout: () => Promise<void>;
}) {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur supports-backdrop-filter:bg-background/60">
      <div className="flex h-14 items-center gap-2 px-3 md:px-6">
        <Link href="/" className="flex items-center gap-2 md:hidden shrink-0">
          <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <LineChart className="size-3.5" />
          </div>
        </Link>

        <nav className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto md:hidden">
          {NAV_ITEMS.map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-1 rounded-md px-1.5 py-1.5 text-[11px] font-medium whitespace-nowrap transition-colors",
                  active
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-secondary/60"
                )}
              >
                <Icon className="size-3.5 shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-1 shrink-0">
          <ThemeToggle />
          {isLoggedIn && (
            <form
              action={onLogout}
              onSubmit={(e) => {
                if (!confirm("ログアウトしますか？")) e.preventDefault();
              }}
            >
              <Button variant="ghost" size="icon" className="size-8" type="submit" aria-label="ログアウト">
                <LogOut className="size-4" />
              </Button>
            </form>
          )}
        </div>
      </div>
    </header>
  );
}
