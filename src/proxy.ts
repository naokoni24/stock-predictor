import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value)
        );
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options)
        );
      },
    },
  });

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const PUBLIC_PATHS = ["/login", "/forgot-password", "/reset-password"];

  // getUser()が更新・削除した認証Cookieを、リダイレクト先へのレスポンスにも引き継ぐ。
  // NextResponse.redirectを直接返すとsetAllで更新したCookieが失われる。
  const redirectWithCookies = (url: URL) => {
    const redirect = NextResponse.redirect(url);
    response.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
    return redirect;
  };

  if (!user && !PUBLIC_PATHS.includes(request.nextUrl.pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return redirectWithCookies(url);
  }

  if (user && request.nextUrl.pathname === "/login") {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    return redirectWithCookies(url);
  }

  return response;
}

export const config = {
  // /api配下(src/app/api/cron/repair-check等)はSupabaseセッションを持たない
  // 外部からのAPI呼び出し(Vercel Cron等)が対象で、ここで/loginへリダイレクトすると
  // 呼び出し元が期待するJSONではなくHTMLが返ってしまうため、authミドルウェアの対象外にする。
  // API側の認証は各Route Handlerが個別に行う(cron/repair-checkはCRON_SECRETで検証)。
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|apple-icon|icon|manifest|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
