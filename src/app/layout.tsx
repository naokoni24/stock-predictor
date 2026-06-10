import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { createClient } from "@/lib/supabase-server";
import { logout } from "./login/actions";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "株価予測アプリ",
  description: "本日のおすすめ株と保有株の売り時をチェック",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <html
      lang="ja"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-zinc-950 text-zinc-100">
        <header className="border-b border-zinc-800 border-zinc-800 bg-zinc-900">
          <nav className="max-w-3xl mx-auto flex items-center gap-6 px-4 py-3 text-sm font-medium">
            <Link href="/">本日のおすすめ</Link>
            <Link href="/holdings">保有株</Link>
            <Link href="/stocks">登録銘柄一覧</Link>
            {user && (
              <form action={logout} className="ml-auto">
                <button
                  type="submit"
                  className="text-zinc-500 hover:text-zinc-200"
                >
                  ログアウト
                </button>
              </form>
            )}
          </nav>
        </header>
        <main className="flex-1 max-w-3xl mx-auto w-full px-4 py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
