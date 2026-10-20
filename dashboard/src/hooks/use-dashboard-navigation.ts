import { useLocation, useNavigate } from "@tanstack/react-router";
import { key, type Dataset, type Row } from "../data";
import { views, type View } from "../navigation";

export function useDashboardNavigation() {
  const location = useLocation();
  const routerNavigate = useNavigate();
  const view: View = views.find(([id]) => location.pathname === `/${id}`)?.[0] ?? "overview";
  const p = new URLSearchParams(location.searchStr);
  function navigate(changes: Record<string, string | null>, nextView: View = view) {
    void routerNavigate({
      to: `/${nextView}`,
      search: (previous) => {
        const next = nextView === view ? { ...previous } : {};
        for (const [name, value] of Object.entries(changes)) {
          if (value === null) delete next[name];
          else next[name] = value;
        }
        return next;
      },
    });
  }
  function select(row: Row, type: Dataset, tab = "details") {
    navigate({ selected: key(row), selection: type, tab });
  }
  return { view, p, navigate, select, selectedId: p.get("selected") };
}
