import { createContext, useContext, useState } from "react";
import { useQueries, useQuery, type QueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "@tanstack/react-router";
import { datasetsForView, type Dataset, type Row } from "../data";
import { useDashboardNavigation } from "./use-dashboard-navigation";

async function get<T>(name: string): Promise<T> {
  const response = await fetch("/api/" + name);
  if (!response.ok)
    throw new Error(
      response.status === 401
        ? "Open the current launch URL printed by protein-detective dashboard to authenticate."
        : `Could not load ${name} (${response.status}).`,
    );

  return response.json();
}

const datasets: Dataset[] = ["candidates", "fitting", "refinements", "provenance"];

export function useSessionData(client: QueryClient) {
  const { view, p } = useDashboardNavigation();
  const routerNavigate = useNavigate();
  const hash = useLocation({ select: (location) => location.hash });
  const [token] = useState(() => new URLSearchParams(hash).get("token"));
  const summary = useQuery(
    {
      queryKey: ["summary"],
      queryFn: async () => {
        if (token) {
          const response = await fetch("/api/auth", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
          });
          if (!response.ok)
            throw new Error(
              "Authentication failed. Open the current launch URL printed by protein-detective dashboard.",
            );
          await routerNavigate({ to: ".", search: true, hash: "", replace: true });
        }
        return get<Row>("summary");
      },
    },
    client,
  );
  const needed = datasetsForView(view, p.get("selected"));
  const queries = useQueries(
    {
      queries: datasets.map((name) => ({
        queryKey: [name],
        queryFn: () => get<Row[]>(name),
        enabled: summary.isSuccess && needed.includes(name),
      })),
    },
    client,
  );
  const data: Partial<Record<Dataset, Row[]>> = Object.fromEntries(
    queries.flatMap((query, i) => (query.data ? [[datasets[i], query.data]] : [])),
  );
  const error =
    summary.error ?? queries.find((query, i) => needed.includes(datasets[i]) && query.error)?.error;

  return {
    ready: summary.isSuccess,
    error: error?.message ?? "",
    data,
    summary: summary.data ?? {},
    retry: () => client.refetchQueries({ predicate: (query) => query.state.status === "error" }),
  };
}

export const SessionContext = createContext<ReturnType<typeof useSessionData> | null>(null);

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("SessionProvider is required");

  return session;
}
