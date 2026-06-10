import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ja"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-zinc-50 text-zinc-900">
        <header className="border-b bg-white">
          <nav className="max-w-3xl mx-auto flex gap-6 px-4 py-3 text-sm font-medium">
            <Link href="/">本日のおすすめ</Link>
            <Link href="/holdings">保有株</Link>
            <Link href="/stocks">登録銘柄一覧</Link>
          </nav>
        </header>
        <main className="flex-1 max-w-3xl mx-auto w-full px-4 py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
