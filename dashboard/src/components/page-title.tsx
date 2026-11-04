import { type ReactNode } from "react";
import { views } from "../navigation";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";

export function PageTitle({ children }: { children?: ReactNode }) {
  const { view } = useDashboardNavigation();
  return (
    <div className="page-title">
      <div>
        <p className="eyebrow">PROTEIN DETECTIVE / {view.toUpperCase()}</p>
        <h1>{views.find(([id]) => id === view)?.[1]}</h1>
      </div>
      {children}
    </div>
  );
}
