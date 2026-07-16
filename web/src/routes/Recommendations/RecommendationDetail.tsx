import { useParams, Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ActionBadge } from "@/components/ActionBadge";
import { PriceTargetCard } from "@/components/PriceTargetCard";
import { RationaleList } from "@/components/RationaleList";
import { useRecommendationDetail } from "@/hooks/useApi";

export function RecommendationDetail() {
  const { instrumentId } = useParams<{ instrumentId: string }>();
  const id = instrumentId ? Number(instrumentId) : undefined;
  const { data, isLoading } = useRecommendationDetail(id);

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const { instrument, close, recommendation } = data;

  return (
    <div className="space-y-6">
      <Link to="/recommendations">
        <Button variant="ghost" size="sm" className="gap-1 pl-0">
          <ArrowLeft className="h-4 w-4" /> Back to recommendations
        </Button>
      </Link>

      <div>
        <h1 className="text-2xl font-semibold">
          {instrument.symbol} <span className="font-normal text-muted-foreground">— {instrument.name}</span>
        </h1>
        <p className="text-sm text-muted-foreground">
          {instrument.sector ?? "Unclassified sector"}
          {close && ` · Close (${close.trade_date}): ${close.close.toFixed(2)}`}
        </p>
      </div>

      {!recommendation ? (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground">
            No recommendation computed yet for this instrument.
          </CardContent>
        </Card>
      ) : (
        <Tabs defaultValue="short">
          <TabsList>
            <TabsTrigger value="short">Short-term</TabsTrigger>
            <TabsTrigger value="long">Long-term</TabsTrigger>
          </TabsList>

          <TabsContent value="short" className="space-y-4">
            <div className="flex items-center gap-3">
              <ActionBadge action={recommendation.short_term_action} />
              <span className="text-sm text-muted-foreground">
                score {recommendation.short_term_score !== null ? recommendation.short_term_score.toFixed(2) : "—"}
              </span>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Justification</CardTitle>
                </CardHeader>
                <CardContent>
                  <RationaleList
                    topReasons={recommendation.short_term_top_reasons}
                    rationale={recommendation.short_term_rationale}
                  />
                </CardContent>
              </Card>
              <PriceTargetCard
                close={close?.close ?? null}
                target={recommendation.short_term_price_targets.target}
                stop={recommendation.short_term_price_targets.stop}
                atr14={recommendation.atr_14}
              />
            </div>
          </TabsContent>

          <TabsContent value="long" className="space-y-4">
            <div className="flex items-center gap-3">
              <ActionBadge action={recommendation.long_term_action} />
              <span className="text-sm text-muted-foreground">
                score {recommendation.long_term_score !== null ? recommendation.long_term_score.toFixed(2) : "—"}
              </span>
            </div>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Justification</CardTitle>
              </CardHeader>
              <CardContent>
                <RationaleList
                  topReasons={recommendation.long_term_top_reasons}
                  rationale={recommendation.long_term_rationale}
                />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
