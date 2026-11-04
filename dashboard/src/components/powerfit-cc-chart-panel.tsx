import { Scatter } from "../charts";
import { type Row } from "../data";

export function PowerfitCcChartPanel({
  rows,
  onSelect,
}: {
  rows: Row[];
  onSelect: (row: Row) => void;
}) {
  return (
    <section className="chart-section">
      <div>
        <h2>PowerFit CC comparison</h2>
        <p className="muted">
          All {rows.length.toLocaleString()} matching members, before top-N selection and
          pagination.
        </p>
        <p>Points above the diagonal have a higher (better) PowerFit CC.</p>
      </div>
      <Scatter rows={rows} onSelect={onSelect} metric="cc" />
    </section>
  );
}
