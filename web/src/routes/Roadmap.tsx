import * as React from "react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRoadmap } from "@/hooks/useApi";
import type { RoadmapItem } from "@/api/types";

function groupByDomain(items: RoadmapItem[]): Map<string, RoadmapItem[]> {
  const map = new Map<string, RoadmapItem[]>();
  for (const item of items) {
    if (!map.has(item.domain)) map.set(item.domain, []);
    map.get(item.domain)!.push(item);
  }
  return map;
}

export function Roadmap() {
  const { data, isLoading } = useRoadmap();
  const grouped = React.useMemo(() => groupByDomain(data?.items ?? []), [data]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Roadmap & known gaps</h1>
        <p className="text-sm text-muted-foreground">
          What this project has deliberately deferred or found dead, by domain — transcribed from the project's own
          documented scope decisions.
        </p>
      </div>

      {isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        Array.from(grouped.entries()).map(([domain, items]) => (
          <Card key={domain}>
            <CardHeader>
              <CardTitle className="text-base">{domain}</CardTitle>
            </CardHeader>
            <CardContent>
              <Accordion type="single" collapsible>
                {items.map((item, i) => (
                  <AccordionItem key={i} value={String(i)}>
                    <AccordionTrigger>
                      <div className="flex items-center gap-2 text-left">
                        <Badge variant={item.status === "DROPPED" ? "destructive" : "secondary"}>{item.status}</Badge>
                        {item.title}
                      </div>
                    </AccordionTrigger>
                    <AccordionContent>
                      <p className="text-sm text-muted-foreground">{item.description}</p>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
