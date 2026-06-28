import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { createClient } from "@/lib/supabase-server";
import { logout } from "./login/actions";
import { ThemeProvider } from "@/components/theme-provider";
import { SiteSidebar } from "@/components/site-sidebar";
import { SiteHeader } from "@/components/site-header";
import { InactivityLogout } from "@/components/inactivity-logout";
import { Suspense } from "react";
import { NavigationProgress } from "@/components/navigation-progress";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Stock Signal | 株価予測ダッシュボード",
  description: "本日のおすすめ株と保有株の売り時をAIでチェック",
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
    data: { session },
  } = await supabase.auth.getSession();
  const user = session?.user ?? null;

  return (
    <html
      lang="ja"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-foreground">
        {/* 描画前に無操作/セッション期限を判定し、期限切れならコンテンツを隠す。
            InactivityLogout がサインアウトして /login へ遷移するまでのチラ見えを防ぐ。 */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var p=location.pathname;if(p==='/login'||p==='/forgot-password'||p==='/reset-password')return;var s=localStorage.getItem('sessionStartedAt'),l=localStorage.getItem('lastActivityAt');if(!s||!l)return;var n=Date.now();if(n-Number(s)>=43200000||n-Number(l)>=1800000){document.documentElement.setAttribute('data-auth-expired','');}}catch(e){}})();`,
          }}
        />
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          {user && <InactivityLogout />}
          <Suspense fallback={null}>
            <NavigationProgress />
          </Suspense>
          <div className="flex min-h-svh">
            {user && <SiteSidebar />}
            <div className="flex min-w-0 flex-1 flex-col">
              {user && <SiteHeader onLogout={logout} />}
              <main className="flex-1 mx-auto w-full max-w-6xl px-4 py-6 md:px-8 md:py-8">
                {children}
              </main>
            </div>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
