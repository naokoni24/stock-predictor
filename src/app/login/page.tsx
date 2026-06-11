import Link from "next/link";
import { LineChart } from "lucide-react";
import { login } from "./actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { SubmitButton } from "@/components/login-submit-button";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;

  return (
    <div className="flex flex-col items-center justify-center flex-1 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center gap-2">
          <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <LineChart className="size-5" />
          </div>
          <CardTitle className="text-xl">AI Stock Signal にログイン</CardTitle>
        </CardHeader>
        <CardContent>
          <form action={login} className="flex flex-col gap-4">
            {error && <p className="text-bearish text-sm text-center">{error}</p>}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="email">メールアドレス</Label>
              <Input id="email" name="email" type="email" required />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">パスワード</Label>
              <Input id="password" name="password" type="password" required />
            </div>

            <SubmitButton label="ログイン" pendingLabel="ログイン中..." />
          </form>

          <p className="text-sm text-center text-muted-foreground mt-4">
            <Link href="/forgot-password" className="font-medium text-foreground hover:underline">
              パスワードをお忘れですか？
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
