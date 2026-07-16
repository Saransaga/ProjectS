import * as React from "react";
import { useNavigate } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ActionBadge } from "@/components/ActionBadge";
import { useRecommendations } from "@/hooks/useApi";
import type { Action } from "@/api/types";

const ACTION_FILTERS: { label: string; actions?: Action[] }[] = [
  { label: "All" },
  { label: "Buy ideas", actions: ["STRONG_BUY", "BUY"] },
  { label: "Sell ideas", actions: ["SELL", "STRONG_SELL"] },
  { label: "Hold", actions: ["HOLD"] },
];

export function RecommendationsList() {
  const navigate = useNavigate();
  const [horizon, setHorizon] = React.useState<"short" | "long">("short");
  const [filterIdx, setFilterIdx] = React.useState(0);

  const { data, isLoading } = useRecommendations({
    horizon,
    actions: ACTION_FILTERS[filterIdx].actions,
    sort: "score_desc",
    limit: 100,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Recommendations</h1>
        <p className="text-sm text-muted-foreground">
          {data?.as_of_date ? `As of ${data.as_of_date}` : "Latest computed recommendation per instrument."}
        </p>
      </div>

      <div className="flex items-center justify-between">
        <Tabs value={horizon} onValueChange={(v) => setHorizon(v as "short" | "long")}>
          <TabsList>
            <TabsTrigger value="short">Short-term</TabsTrigger>
            <TabsTrigger value="long">Long-term</TabsTrigger>
          </TabsList>
        </Tabs>
        <Tabs value={String(filterIdx)} onValueChange={(v) => setFilterIdx(Number(v))}>
          <TabsList>
            {ACTION_FILTERS.map((f, i) => (
              <TabsTrigger key={f.label} value={String(i)}>
                {f.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{data?.total ?? 0} instruments</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Sector</TableHead>
                  <TableHead>Score</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((item) => (
                  <TableRow
                    key={item.instrument_id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/recommendations/${item.instrument_id}`)}
                  >
                    <TableCell className="font-semibold">{item.symbol}</TableCell>
                    <TableCell className="text-muted-foreground">{item.name}</TableCell>
                    <TableCell className="text-muted-foreground">{item.sector ?? "—"}</TableCell>
                    <TableCell className="tabular-nums">{item.score !== null ? item.score.toFixed(2) : "—"}</TableCell>
                    <TableCell>
                      <ActionBadge action={item.action} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
