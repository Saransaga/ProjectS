import * as React from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useOutcomeSummary, useOutcomesByAction, useOutcomesByComponent } from "@/hooks/useApi";

function pct(v: number | null): string {
  return v === null ? "—" : `${(v * 100).toFixed(0)}%`;
}

export function PerformanceOverview() {
  const [horizon] = React.useState<"short">("short"); // long-term outcome tracking isn't built yet — see Roadmap
  const { data: summary, isLoading: loadingSummary } = useOutcomeSummary(horizon);
  const { data: byAction, isLoading: loadingByAction } = useOutcomesByAction(horizon);
  const { data: byComponent } = useOutcomesByComponent(horizon);

  const chartData = (byAction?.items ?? []).map((i) => ({
    name: i.action,
    winRate: i.win_rate !== null ? Math.round(i.win_rate * 100) : 0,
    total: i.total,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Performance</h1>
        <p className="text-sm text-muted-foreground">
          How short-term calls actually played out — resolved against real price action, not just the call itself.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Win rate</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{loadingSummary ? <Skeleton className="h-8 w-16" /> : pct(summary?.win_rate ?? null)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Open calls</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{loadingSummary ? <Skeleton className="h-8 w-10" /> : summary?.counts.OPEN ?? 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Avg days to resolve</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {loadingSummary ? <Skeleton className="h-8 w-10" /> : summary?.avg_days_to_resolution?.toFixed(1) ?? "—"}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total tracked</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{loadingSummary ? <Skeleton className="h-8 w-10" /> : summary?.total ?? 0}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Win rate by action bucket</CardTitle>
        </CardHeader>
        <CardContent>
          {loadingByAction ? (
            <Skeleton className="h-64 w-full" />
          ) : chartData.length === 0 ? (
            <p className="text-sm text-muted-foreground">No resolved calls yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="name" fontSize={12} />
                <YAxis unit="%" fontSize={12} />
                <ChartTooltip formatter={(value: number, name: string) => [name === "winRate" ? `${value}%` : value, name]} />
                <Bar dataKey="winRate" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Win rate by dominant signal</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {(byComponent?.items ?? []).map((c) => (
              <div key={c.component} className="flex items-center justify-between text-sm">
                <span className="font-mono text-xs text-muted-foreground">{c.component}</span>
                <span>
                  {pct(c.win_rate)} <span className="text-muted-foreground">({c.total} calls)</span>
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
