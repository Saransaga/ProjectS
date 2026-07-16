import * as React from "react";

import { api } from "@/api/client";

interface AuthContextValue {
  authenticated: boolean | null; // null = still checking
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authenticated, setAuthenticated] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    api
      .get<{ authenticated: boolean }>("/auth/session")
      .then((res) => setAuthenticated(res.authenticated))
      .catch(() => setAuthenticated(false));
  }, []);

  const login = React.useCallback(async (password: string) => {
    await api.post("/auth/login", { password });
    setAuthenticated(true);
  }, []);

  const logout = React.useCallback(async () => {
    await api.post("/auth/logout");
    setAuthenticated(false);
  }, []);

  return <AuthContext.Provider value={{ authenticated, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
