"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LineChart } from "lucide-react";
import { createClient } from "@/lib/supabase-browser";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ password });

    setSubmitting(false);

    if (error) {
      setError(error.message);
      return;
    }

    // パスワード再設定はこのタブで明示的に認証した操作なので、
    // トップページ遷移後にブラウザ再起動由来のCookieと誤判定して
    // 即時ログアウトしないよう、現在のタブを有効な認証セッションとして記録する。
    sessionStorage.setItem("authBrowserSession", "active");
    setDone(true);
    setTimeout(() => router.push("/"), 1500);
  };

  return (
    <div className="flex flex-col items-center justify-center flex-1 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center gap-2">
          <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <LineChart className="size-5" />
          </div>
          <CardTitle className="text-xl">新しいパスワードを設定</CardTitle>
        </CardHeader>
        <CardContent>
          {done ? (
            <p className="text-sm text-center text-muted-foreground">
              パスワードを更新しました。トップページに移動します...
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              {error && <p className="text-bearish text-sm text-center">{error}</p>}

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password">新しいパスワード</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  required
                  minLength={6}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>

              <Button type="submit" className="mt-2" disabled={submitting}>
                {submitting ? "更新中..." : "パスワードを更新"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
