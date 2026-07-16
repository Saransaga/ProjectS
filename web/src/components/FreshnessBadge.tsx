import { Badge } from "@/components/ui/badge";
import type { Freshness } from "@/api/types";

const VARIANT: Record<Freshness, "success" | "warning" | "destructive" | "outline"> = {
  FRESH: "success",
  DUE: "warning",
  STALE: "destructive",
  UNKNOWN: "outline",
};

export function FreshnessBadge({ freshness }: { freshness: Freshness }) {
  return <Badge variant={VARIANT[freshness]}>{freshness}</Badge>;
}
