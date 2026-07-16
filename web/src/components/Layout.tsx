import { NavLink, Outlet } from "react-router-dom";
import { Activity, BarChart3, Compass, LineChart, LogOut, TrendingUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV: { to: string; label: string; icon: typeof Activity; end: boolean }[] = [
  { to: "/", label: "Overview", icon: Activity, end: true },
  { to: "/recommendations", label: "Recommendations", icon: TrendingUp, end: false },
  { to: "/performance", label: "Performance", icon: LineChart, end: false },
  { to: "/data-health", label: "Data health", icon: BarChart3, end: false },
  { to: "/roadmap", label: "Roadmap", icon: Compass, end: false },
];

export function Layout() {
  const { logout } = useAuth();

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r bg-card px-3 py-4">
        <div className="mb-6 px-2 text-lg font-semibold">Trading Dashboard</div>
        <nav className="space-y-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-2 py-2 text-sm font-medium transition-colors",
                  isActive ? "bg-secondary text-secondary-foreground" : "text-muted-foreground hover:bg-accent",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-6 px-2">
          <Button variant="ghost" size="sm" className="w-full justify-start gap-2" onClick={() => logout()}>
            <LogOut className="h-4 w-4" />
            Log out
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden p-6">
        <Outlet />
      </main>
    </div>
  );
}
