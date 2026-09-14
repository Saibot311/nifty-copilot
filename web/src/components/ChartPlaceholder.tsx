export function ChartPlaceholder() {
  return (
    <div className="flex h-64 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-800 bg-zinc-900/40 text-zinc-600">
      <span className="text-sm">15-minute candle chart goes here</span>
      <span className="text-xs text-zinc-700">
        Wired up in a later phase once real market data is connected
      </span>
    </div>
  );
}
