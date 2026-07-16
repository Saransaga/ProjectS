import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OpenPositions } from "./OpenPositions";
import { PerformanceOverview } from "./PerformanceOverview";

export function Performance() {
  return (
    <Tabs defaultValue="overview">
      <TabsList className="mb-4">
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="open">Open positions</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <PerformanceOverview />
      </TabsContent>
      <TabsContent value="open">
        <OpenPositions />
      </TabsContent>
    </Tabs>
  );
}
