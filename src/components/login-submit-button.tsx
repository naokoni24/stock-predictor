"use client";

import { useFormStatus } from "react-dom";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export function LoginSubmitButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" className="mt-2" disabled={pending}>
      {pending ? (
        <>
          <Loader2 className="size-4 animate-spin" />
          ログイン中...
        </>
      ) : (
        "ログイン"
      )}
    </Button>
  );
}
