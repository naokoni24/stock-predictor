"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase-server";
import { authErrorMessage } from "@/lib/auth-errors";

export async function login(formData: FormData) {
  const email = formData.get("email") as string;
  const password = formData.get("password") as string;

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) {
    redirect(
      `/login?error=${encodeURIComponent(authErrorMessage(error, "ログインできませんでした。時間をおいて再度お試しください。"))}`
    );
  }

  redirect("/");
}

export async function logout() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}
