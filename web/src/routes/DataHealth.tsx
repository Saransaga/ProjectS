import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useKnownGaps, useSourceHealth } from "@/hooks/useApi";

export function DataHealth() {
  const { data, isLoading } = useSourceHealth();
  const { data: gaps } = useKnownGaps();

  const sortedSources = [...(data?.news_sources ?? [])].sort((a, b) => a.item_count - b.item_count);
  const sortedJobs = [...(data?.jobs ?? [])].sort((a, b) => (a.avg_rows_per_run ?? 0) - (b.avg_rows_per_run ?? 0));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Data source health</h1>
        <p className="text-sm text-muted-foreground">
          Least-used sources first — a low count here can mean organic disuse, or a documented, known-dead source
          below.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>News sources ({data?.window_days ?? 30}-day window)</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Source</TableHead>
                  <TableHead>Items</TableHead>
                  <TableHead>Credibility weight</TableHead>
                  <TableHead>Latest published</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedSources.map((s) => (
                  <TableRow key={s.source_type}>
                    <TableCell className="font-mono text-xs">{s.source_type}</TableCell>
                    <TableCell className="tabular-nums">{s.item_count}</TableCell>
                    <TableCell className="tabular-nums">{s.credibility_weight?.toFixed(2) ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {s.latest_published_at ? new Date(s.latest_published_at).toLocaleString() : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Jobs by average rows per run (lowest first)</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Job</TableHead>
                  <TableHead>Successful runs</TableHead>
                  <TableHead>Total rows</TableHead>
                  <TableHead>Avg rows/run</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedJobs.map((j) => (
                  <TableRow key={j.job_name}>
                    <TableCell className="font-mono text-xs">{j.job_name}</TableCell>
                    <TableCell className="tabular-nums">{j.successful_runs}</TableCell>
                    <TableCell className="tabular-nums">{j.total_rows_ingested}</TableCell>
                    <TableCell className="tabular-nums">{j.avg_rows_per_run?.toFixed(1) ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Known dead/blocked sources</CardTitle>
        </CardHeader>
        <CardContent>
          <Accordion type="single" collapsible>
            {(gaps?.items ?? []).map((item, i) => (
              <AccordionItem key={i} value={String(i)}>
                <AccordionTrigger>
                  <div className="flex items-center gap-2 text-left">
                    <Badge variant={item.status === "DROPPED" ? "destructive" : "secondary"}>{item.status}</Badge>
                    {item.title}
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <p className="text-sm text-muted-foreground">{item.description}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{item.domain}</p>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </CardContent>
      </Card>
    </div>
  );
}
