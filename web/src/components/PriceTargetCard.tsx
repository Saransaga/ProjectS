import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { PriceLevel } from "@/api/types";

function LevelRow({ label, level, atr }: { label: string; level: PriceLevel | null; atr?: number }) {
  if (!level) {
    return (
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="text-muted-foreground">no data</span>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">
        {label}
        {level.projected && (
          <Badge variant="outline" className="ml-2 text-[10px]">
            ATR-projected
          </Badge>
        )}
      </span>
      <span className="tabular-nums font-medium">
        {level.price.toFixed(2)}
        {level.strength ? ` (touched ${level.strength}x)` : ""}
      </span>
    </div>
  );
}

export function PriceTargetCard({
  close,
  target,
  stop,
  atr14,
}: {
  close: number | null;
  target: PriceLevel | null;
  stop: PriceLevel | null;
  atr14?: number | null;
}) {
  const paceDays =
    target && close !== null && atr14 ? Math.max(1, Math.round(Math.abs(target.price - close) / atr14)) : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">Price target & exit</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {close !== null && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Current close</span>
            <span className="tabular-nums font-semibold">{close.toFixed(2)}</span>
          </div>
        )}
        <LevelRow label="Target" level={target} />
        <LevelRow label="Stop / exit" level={stop} />
        {paceDays !== null && (
          <p className="pt-1 text-xs text-muted-foreground">
            ~{paceDays} trading day(s) to target at the recent ATR pace — an estimate, not a forecast.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
