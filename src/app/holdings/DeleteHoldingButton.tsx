"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

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
    <button
      onClick={handleDelete}
      disabled={loading}
      className="text-xs text-zinc-400 hover:text-red-600 disabled:opacity-50"
    >
      削除
    </button>
  );
}
