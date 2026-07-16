import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import type { Rationale } from "@/api/types";

/** Top reasons as prose (already rendered server-side via
 * recommendation/rationale_text.py::top_reasons), plus every component's raw
 * subscore in a collapsible breakdown for anyone who wants the full picture
 * behind the headline reasons. */
export function RationaleList({ topReasons, rationale }: { topReasons: string[]; rationale: Rationale | null }) {
  if (!rationale) {
    return <p className="text-sm text-muted-foreground">No rationale available.</p>;
  }

  return (
    <div className="space-y-3">
      {rationale.insufficient_data && (
        <p className="text-sm text-amber-600 dark:text-amber-400">
          Insufficient data for a confident score ({Math.round(rationale.available_weight * 100)}% of the weight
          budget had real data).
        </p>
      )}
      <ul className="space-y-1 text-sm">
        {topReasons.map((reason, i) => (
          <li key={i}>&bull; {reason}</li>
        ))}
      </ul>
      <Accordion type="single" collapsible>
        <AccordionItem value="components">
          <AccordionTrigger className="text-sm text-muted-foreground">
            Full component breakdown ({rationale.components.length})
          </AccordionTrigger>
          <AccordionContent>
            <table className="w-full text-sm">
              <tbody>
                {rationale.components.map((c) => (
                  <tr key={c.name} className="border-b last:border-0">
                    <td className="py-1 pr-2 font-mono text-xs text-muted-foreground">{c.name}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">
                      {c.subscore === null ? "—" : c.subscore.toFixed(2)}
                    </td>
                    <td className="py-1 pr-2 text-right text-xs text-muted-foreground tabular-nums">
                      w={c.weight.toFixed(2)}
                    </td>
                    <td className="py-1 text-right tabular-nums">
                      {c.weighted === null ? "no data" : c.weighted.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
