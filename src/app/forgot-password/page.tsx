import Link from "next/link";
import { LineChart } from "lucide-react";
import { sendResetEmail } from "./actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { SubmitButton } from "@/components/login-submit-button";

export default async function ForgotPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; sent?: string }>;
}) {
  const { error, sent } = await searchParams;

  return (
    <div className="flex flex-col items-center justify-center flex-1 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center gap-2">
          <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <LineChart className="size-5" />
          </div>
          <CardTitle className="text-xl">パスワードをリセット</CardTitle>
        </CardHeader>
        <CardContent>
          {sent ? (
            <p className="text-sm text-center text-muted-foreground">
              パスワード再設定用のメールを送信しました。メール内のリンクから新しいパスワードを設定してください。
            </p>
          ) : (
            <form action={sendResetEmail} className="flex flex-col gap-4">
              {error && <p className="text-bearish text-sm text-center">{error}</p>}

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email">メールアドレス</Label>
                <Input id="email" name="email" type="email" required />
              </div>

              <SubmitButton label="リセットメールを送信" pendingLabel="送信中..." />
            </form>
          )}

          <p className="text-sm text-center text-muted-foreground mt-4">
            <Link href="/login" className="font-medium text-foreground hover:underline">
              ログイン画面に戻る
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
