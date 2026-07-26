"use server";

import { redirect } from "next/navigation";
import { headers } from "next/headers";
import { createClient } from "@/lib/supabase-server";

function getRequestOrigin(headerList: Awaited<ReturnType<typeof headers>>) {
  const origin = headerList.get("origin");
  if (origin) {
    return origin;
  }

  const host = headerList.get("x-forwarded-host") ?? headerList.get("host");
  if (host) {
    const protocol =
      headerList.get("x-forwarded-proto") ??
      (host.startsWith("localhost") || host.startsWith("127.0.0.1")
        ? "http"
        : "https");
    return `${protocol}://${host}`;
  }

  const vercelUrl =
    process.env.VERCEL_PROJECT_PRODUCTION_URL ?? process.env.VERCEL_URL;
  return vercelUrl ? `https://${vercelUrl}` : null;
}

export async function sendResetEmail(formData: FormData) {
  const email = formData.get("email") as string;

  const supabase = await createClient();
  const headerList = await headers();
  const origin = getRequestOrigin(headerList);

  if (!origin) {
    redirect(
      `/forgot-password?error=${encodeURIComponent("再設定先URLを判定できませんでした。")}`
    );
  }

  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: new URL("/reset-password", origin).toString(),
  });

  if (error) {
    redirect(`/forgot-password?error=${encodeURIComponent(error.message)}`);
  }

  redirect("/forgot-password?sent=1");
}
