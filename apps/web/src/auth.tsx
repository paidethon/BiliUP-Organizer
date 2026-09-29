import { QueryClient, useQuery } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { api } from "./api";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000, refetchOnWindowFocus: false } },
});

interface AuthState {
  username: string | null;
  demoMode: boolean;
}

const AuthContext = createContext<AuthState>({ username: null, demoMode: false });

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: () => api<{ username: string; demo_mode: boolean }>("/auth/me"),
  });
  if (isLoading) return null;
  return (
    <AuthContext.Provider value={{ username: data?.username ?? null, demoMode: data?.demo_mode ?? false }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
