import { Link, Outlet } from "@tanstack/react-router";
import { views } from "./navigation";
import { useDashboardNavigation } from "./hooks/use-dashboard-navigation";
import { useSession } from "./hooks/use-session-data";
import { SessionProvider } from "./components/session-provider";
import { DetailsPanel } from "./components/details-panel";
import { ThemeToggle } from "./components/theme-toggle";

function SessionLayout() {
  const { ready, error } = useSession();
  const { view } = useDashboardNavigation();
  return (
    <>
      <header>
        <div className="brand">
          <span className="logo">⌕</span>
          <div>
            <strong>Protein Detective</strong>
            <small>Session explorer</small>
          </div>
        </div>
        <div className="header-actions">
          <ThemeToggle />
          <span className="snapshot">Read-only snapshot</span>
        </div>
      </header>
      <nav aria-label="Main navigation">
        {views.map(([id, title]) => (
          <Link key={id} to={`/${id}`} search={{}} aria-current={view === id ? "page" : undefined}>
            {title}
          </Link>
        ))}
      </nav>
      {error ? (
        <div className="error" role="alert">
          {error}
        </div>
      ) : !ready ? (
        <p className="empty">Authenticating and loading session…</p>
      ) : (
        <div className="workspace">
          <main>
            <Outlet />
          </main>
          <DetailsPanel />
        </div>
      )}
      <footer>
        Stable session snapshot · Do not modify the session directory while this dashboard is
        running.
      </footer>
    </>
  );
}

export function App() {
  return (
    <SessionProvider>
      <SessionLayout />
    </SessionProvider>
  );
}
