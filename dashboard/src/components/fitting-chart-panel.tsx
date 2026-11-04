import { Histogram } from "../charts";
import { type Row } from "../data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";

export function FittingChartPanel({ rows }: { rows: Row[] }) {
  const { p, navigate } = useDashboardNavigation();
  const metric = p.get("metric") || "cc";
  return (
    <section className="chart-section">
      <div>
        <h2>PowerFit score distribution</h2>
        <p className="muted">
          All {rows.length.toLocaleString()} matching solutions, before top-N selection and
          pagination.
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
