import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ActionBadge } from "@/components/ActionBadge";
import { useOpenPositions } from "@/hooks/useApi";
import type { OpenPosition } from "@/api/types";

function progressToward(position: OpenPosition): number {
  const { entry_close, target_price, latest_close } = position;
  if (target_price === null || latest_close === null) return 0;
  const total = Math.abs(target_price - entry_close);
  if (total === 0) return 0;
  const bullish = position.action === "STRONG_BUY" || position.action === "BUY";
  const moved = bullish ? latest_close - entry_close : entry_close - latest_close;
  return Math.max(0, Math.min(100, (moved / total) * 100));
}

export function OpenPositions() {
  const { data, isLoading } = useOpenPositions("short");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Open positions</h1>
        <p className="text-sm text-muted-foreground">
          Every currently-open tracked call and how far it's progressed toward its target.
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : (data?.items.length ?? 0) === 0 ? (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground">No open calls right now.</CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {data?.items.map((position) => (
            <Card key={`${position.instrument_id}-${position.as_of_date}`}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-base">
                  <Link to={`/recommendations/${position.instrument_id}`} className="hover:underline">
                    {position.symbol}
                  </Link>
                  <span className="ml-2 font-normal text-muted-foreground">{position.name}</span>
                </CardTitle>
                <ActionBadge action={position.action} />
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Entry {position.entry_close.toFixed(2)}</span>
                  <span>Now {position.latest_close?.toFixed(2) ?? "—"}</span>
                  <span>Target {position.target_price?.toFixed(2) ?? "—"}</span>
                </div>
                <Progress value={progressToward(position)} />
                <p className="text-xs text-muted-foreground">
                  {position.trading_days_elapsed} trading day(s) open
                  {position.dominant_component && ` · driven by ${position.dominant_component}`}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
