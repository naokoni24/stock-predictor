"use client";

import { Trash2 } from "lucide-react";
import { deleteHolding } from "./actions";
import { Button } from "@/components/ui/button";

export default function DeleteHoldingButton({ id }: { id: number }) {
  const action = deleteHolding.bind(null, id);

  return (
    <form
      action={action}
      onSubmit={(e) => {
        if (!confirm("この保有株を削除しますか？")) {
          e.preventDefault();
        }
      }}
    >
      <Button
        variant="ghost"
        size="icon"
        className="size-8 text-muted-foreground hover:text-bearish"
        aria-label="削除"
      >
        <Trash2 className="size-4" />
      </Button>
    </form>
  );
}
