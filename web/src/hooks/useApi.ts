import { useQuery } from "@tanstack/react-query";

import { api, buildQuery } from "@/api/client";
import type {
  JobFreshness,
  OpenPosition,
  OutcomeBreakdown,
  OutcomeSummary,
  RecommendationDetailResponse,
  RecommendationListResponse,
  RoadmapItem,
  SourceHealthResponse,
} from "@/api/types";

export function useRecommendations(params: {
  horizon?: string;
  actions?: string[];
  sort?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["recommendations", params],
    queryFn: () => api.get<RecommendationListResponse>(`/recommendations${buildQuery(params)}`),
  });
}

export function useRecommendationDetail(instrumentId: number | undefined) {
  return useQuery({
    queryKey: ["recommendation", instrumentId],
    queryFn: () => api.get<RecommendationDetailResponse>(`/recommendations/${instrumentId}`),
    enabled: instrumentId !== undefined,
  });
}

export function useFreshness() {
  return useQuery({
    queryKey: ["freshness"],
    queryFn: () => api.get<{ jobs: JobFreshness[] }>("/freshness"),
    refetchInterval: 60_000,
  });
}

export function useOutcomeSummary(horizon: string = "short") {
  return useQuery({
    queryKey: ["outcomes", "summary", horizon],
    queryFn: () => api.get<OutcomeSummary>(`/outcomes/summary${buildQuery({ horizon })}`),
  });
}

export function useOpenPositions(horizon: string = "short") {
  return useQuery({
    queryKey: ["outcomes", "open", horizon],
    queryFn: () => api.get<{ total: number; items: OpenPosition[] }>(`/outcomes/open${buildQuery({ horizon, limit: 100 })}`),
  });
}

export function useOutcomesByAction(horizon: string = "short") {
  return useQuery({
    queryKey: ["outcomes", "by-action", horizon],
    queryFn: () => api.get<{ items: OutcomeBreakdown[] }>(`/outcomes/by-action${buildQuery({ horizon })}`),
  });
}

export function useOutcomesByComponent(horizon: string = "short") {
  return useQuery({
    queryKey: ["outcomes", "by-component", horizon],
    queryFn: () => api.get<{ items: OutcomeBreakdown[] }>(`/outcomes/by-component${buildQuery({ horizon })}`),
  });
}

export function useSourceHealth() {
  return useQuery({
    queryKey: ["sources", "health"],
    queryFn: () => api.get<SourceHealthResponse>("/sources/health"),
  });
}

export function useKnownGaps() {
  return useQuery({
    queryKey: ["sources", "known-gaps"],
    queryFn: () => api.get<{ items: RoadmapItem[] }>("/sources/known-gaps"),
  });
}

export function useRoadmap() {
  return useQuery({
    queryKey: ["roadmap"],
    queryFn: () => api.get<{ items: RoadmapItem[] }>("/roadmap"),
  });
}
