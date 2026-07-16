import { Badge } from "@/components/ui/badge";
import type { Action } from "@/api/types";

const VARIANT: Record<Action, "success" | "secondary" | "destructive"> = {
  STRONG_BUY: "success",
  BUY: "success",
  HOLD: "secondary",
  SELL: "destructive",
  STRONG_SELL: "destructive",
};

export function ActionBadge({ action }: { action: Action | null }) {
  if (!action) return <Badge variant="outline">No data</Badge>;
  const label = action.replace("_", " ");
  const emphasis = action.startsWith("STRONG_") ? "font-bold" : "";
  return (
    <Badge variant={VARIANT[action]} className={emphasis}>
      {label}
    </Badge>
  );
}
