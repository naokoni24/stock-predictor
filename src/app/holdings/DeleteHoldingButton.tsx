"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";

export default function DeleteHoldingButton({ id }: { id: number }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handleDelete() {
    if (!confirm("この保有株を削除しますか？")) return;
    setLoading(true);
    const { error } = await supabase.from("holdings").delete().eq("id", id);
    setLoading(false);
    if (error) {
      alert(`削除エラー: ${error.message}`);
      return;
    }
    router.refresh();
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-8 text-muted-foreground hover:text-bearish"
      onClick={handleDelete}
      disabled={loading}
      aria-label="削除"
    >
      <Trash2 className="size-4" />
    </Button>
  );
}
