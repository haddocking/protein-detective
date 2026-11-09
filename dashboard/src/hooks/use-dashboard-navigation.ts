import { useLocation, useNavigate } from "@tanstack/react-router";
import { views, type View } from "../navigation";

export function useDashboardNavigation() {
  const location = useLocation();
  const routerNavigate = useNavigate();
  const view: View = views.find(([id]) => location.pathname === `/${id}`)?.[0] ?? "overview";
  const p = new URLSearchParams(location.searchStr);

  function navigate(
    changes: Record<string, string | null>,
    nextView: View = view,
    replace = false,
  ) {
    void routerNavigate({
      to: `/${nextView}`,
      replace,
      // Selecting, sorting, or filtering within a page keeps its scroll position.
      resetScroll: nextView !== view,
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

  return { view, p, navigate, selectedId: p.get("selected") };
}
