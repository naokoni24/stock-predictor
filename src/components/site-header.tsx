"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Wallet,
  ListFilter,
  Activity,
  Bookmark,
  BarChart3,
  LineChart,
  Menu,
  LogOut,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";

const NAV_ITEMS = [
  { href: "/", label: "おすすめ", icon: LayoutDashboard },
  { href: "/holdings", label: "ポートフォリオ", icon: Wallet },
  { href: "/stocks", label: "銘柄一覧", icon: ListFilter },
  { href: "/changes", label: "シグナル変化", icon: Activity },
  { href: "/watchlist", label: "ウォッチリスト", icon: Bookmark },
  { href: "/performance", label: "AI成績", icon: BarChart3 },
];

export function SiteHeader({ onLogout }: { onLogout: () => Promise<void> }) {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur supports-backdrop-filter:bg-background/60">
      <div className="flex h-14 items-center gap-2 px-3 md:px-6">
        <Link href="/" className="flex items-center gap-2 md:hidden shrink-0">
          <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <LineChart className="size-3.5" />
          </div>
        </Link>

        <nav className="min-w-0 flex-1 md:hidden" aria-label="画面メニュー">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className="max-w-full gap-2 px-2"
                aria-label="画面メニューを開く"
              >
                <Menu className="size-4 shrink-0" />
                <span className="truncate">
                  {NAV_ITEMS.find((item) =>
                    item.href === "/"
                      ? pathname === "/"
                      : pathname.startsWith(item.href),
                  )?.label ?? "メニュー"}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-52">
              {NAV_ITEMS.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);
                const Icon = item.icon;
                return (
                  <DropdownMenuItem key={item.href} asChild>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "gap-2",
                        active && "bg-secondary font-semibold",
                      )}
                    >
                      <Icon className="size-4" />
                      {item.label}
                    </Link>
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        </nav>

        <div className="ml-auto flex items-center gap-1 shrink-0">
          <ThemeToggle />
          <form
            action={onLogout}
            onSubmit={(e) => {
              if (!confirm("ログアウトしますか？")) e.preventDefault();
            }}
          >
            <Button
              variant="ghost"
              size="icon"
              className="size-8"
              type="submit"
              aria-label="ログアウト"
            >
              <LogOut className="size-4" />
            </Button>
          </form>
        </div>
      </div>
    </header>
  );
}
