import { useState, type ReactNode } from "react";
import { QueryClient } from "@tanstack/react-query";
import { SessionContext, useSessionData } from "../hooks/use-session-data";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: Infinity, gcTime: Infinity, retry: false } },
      }),
  );
  const session = useSessionData(client);

  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}
