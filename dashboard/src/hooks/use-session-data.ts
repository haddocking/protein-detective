import { createContext, useContext, useEffect, useRef, useState } from "react";
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

export function useSessionData() {
  const { view, p } = useDashboardNavigation();
  const routerNavigate = useNavigate();
  const hash = useLocation({ select: (location) => location.hash });
  const [token] = useState(() => new URLSearchParams(hash).get("token"));
  const selectedId = p.get("selected");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<Partial<Record<Dataset, Row[]>>>({});
  const [summary, setSummary] = useState<Row>({});
  const requested = useRef(new Set<Dataset>());
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
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
        const s = await get<Row>("summary");
        if (!cancelled) {
          setSummary(s);
          setReady(true);
        }
      } catch (e) {
        if (!cancelled) setError(String(e instanceof Error ? e.message : e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, routerNavigate]);
  useEffect(() => {
    if (!ready) return;
    const names = datasetsForView(view, selectedId);
    for (const name of names)
      if (!requested.current.has(name)) {
        requested.current.add(name);
        get<Row[]>(name)
          .then((rows) => setData((current) => ({ ...current, [name]: rows })))
          .catch((e) => setError(e.message));
      }
  }, [ready, view, selectedId]);
  return { ready, error, data, summary };
}
export const SessionContext = createContext<ReturnType<typeof useSessionData> | null>(null);
export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("SessionProvider is required");
  return session;
}
