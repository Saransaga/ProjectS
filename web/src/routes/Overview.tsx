import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { FreshnessBadge } from "@/components/FreshnessBadge";
import { useFreshness } from "@/hooks/useApi";

function cadenceLabel(cadence: { cadence: string; hour?: number; minutes?: number; day_of_week?: number; day_of_month?: number } | null): string {
  if (!cadence) return "unknown";
  switch (cadence.cadence) {
    case "INTRADAY":
      return `every ${cadence.minutes}m`;
    case "DAILY":
      return `daily ~${cadence.hour}:00 IST`;
    case "WEEKLY":
      return "weekly";
    case "MONTHLY":
      return "monthly (1st)";
    default:
      return cadence.cadence;
  }
}

export function Overview() {
  const { data, isLoading } = useFreshness();

  const jobs = data?.jobs ?? [];
  const counts = jobs.reduce(
    (acc, j) => {
      acc[j.freshness] = (acc[j.freshness] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="text-sm text-muted-foreground">Is every data feed up to date, judged against its own expected cadence.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {(["FRESH", "DUE", "STALE", "UNKNOWN"] as const).map((status) => (
          <Card key={status}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{status}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{isLoading ? <Skeleton className="h-8 w-10" /> : counts[status] ?? 0}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Job status</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : (
            <TooltipProvider>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Job</TableHead>
                    <TableHead>Cadence</TableHead>
                    <TableHead>Last run</TableHead>
                    <TableHead>Last status</TableHead>
                    <TableHead>Rows</TableHead>
                    <TableHead>Freshness</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map((job) => (
                    <TableRow key={job.job_name}>
                      <TableCell className="font-mono text-xs">{job.job_name}</TableCell>
                      <TableCell className="text-muted-foreground">{cadenceLabel(job.cadence)}</TableCell>
                      <TableCell>{job.finished_at ? new Date(job.finished_at).toLocaleString() : "never"}</TableCell>
                      <TableCell>{job.status}</TableCell>
                      <TableCell className="tabular-nums">{job.rows_ingested ?? "—"}</TableCell>
                      <TableCell>
                        {job.error ? (
                          <Tooltip>
                            <TooltipTrigger>
                              <FreshnessBadge freshness={job.freshness} />
                            </TooltipTrigger>
                            <TooltipContent>{job.error}</TooltipContent>
                          </Tooltip>
                        ) : (
                          <FreshnessBadge freshness={job.freshness} />
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TooltipProvider>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
