import { SignalChanges } from "@/components/signal-changes";
export default function ChangesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">シグナル変化</h1>
        <p className="text-sm text-muted-foreground mt-1">
          保有中の銘柄を先に表示しています。
        </p>
      </div>
      <SignalChanges />
    </div>
  );
}
