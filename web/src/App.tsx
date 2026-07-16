import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { useAuth } from "@/lib/auth";
import { DataHealth } from "@/routes/DataHealth";
import { Login } from "@/routes/Login";
import { Overview } from "@/routes/Overview";
import { Performance } from "@/routes/Performance";
import { RecommendationDetail } from "@/routes/Recommendations/RecommendationDetail";
import { RecommendationsList } from "@/routes/Recommendations/RecommendationsList";
import { Roadmap } from "@/routes/Roadmap";

function RequireAuth({ children }: { children: ReactNode }) {
  const { authenticated } = useAuth();
  const location = useLocation();

  if (authenticated === null) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading...</div>;
  }
  if (!authenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Overview />} />
        <Route path="/recommendations" element={<RecommendationsList />} />
        <Route path="/recommendations/:instrumentId" element={<RecommendationDetail />} />
        <Route path="/performance" element={<Performance />} />
        <Route path="/data-health" element={<DataHealth />} />
        <Route path="/roadmap" element={<Roadmap />} />
      </Route>
    </Routes>
  );
}
