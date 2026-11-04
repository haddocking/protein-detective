import { Histogram } from "../charts";
import { PanelHelp } from "./panel-help";
import { type Row } from "../data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";

export function FittingChartPanel({ rows }: { rows: Row[] }) {
  const { p, navigate } = useDashboardNavigation();
  const metric = p.get("metric") || "cc";
  return (
    <section className="chart-section">
      <div className="chart-panel-heading">
        <h2>PowerFit score distribution</h2>
        <PanelHelp label="Histogram controls">
          <p>Focus the chart and use arrow keys to inspect score ranges and counts.</p>
        </PanelHelp>
      </div>
      <div>
        <p className="muted">
          {rows.length.toLocaleString()} solutions from the table, across all pages.
        </p>
        <label>
          Metric{" "}
          <select value={metric} onChange={(e) => navigate({ metric: e.target.value })}>
            <option value="cc">PowerFit CC</option>
            <option value="fishz">PowerFit Fisher z</option>
            <option value="relative_z">PowerFit relative z</option>
          </select>
        </label>
      </div>
      <Histogram rows={rows} metric={metric} />
    </section>
  );
}
