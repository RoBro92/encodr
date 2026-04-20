import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type PropsWithChildren, useState } from "react";

import { AuthProvider } from "../features/auth/AuthProvider";
import type { StoredSession } from "../lib/auth/storage";

type AppProvidersProps = PropsWithChildren<{
  initialSession?: StoredSession | null;
  hydrateFromStorage?: boolean;
}>;

export function AppProviders({
  children,
  initialSession,
  hydrateFromStorage,
}: AppProvidersProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider initialSession={initialSession} hydrateFromStorage={hydrateFromStorage}>
        {children}
      </AuthProvider>
    </QueryClientProvider>
  );
}
