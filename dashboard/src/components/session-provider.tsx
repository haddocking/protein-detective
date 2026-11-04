import { type ReactNode } from "react";
import { SessionContext, useSessionData } from "../hooks/use-session-data";

export function SessionProvider({ children }: { children: ReactNode }) {
  const session = useSessionData();
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}
