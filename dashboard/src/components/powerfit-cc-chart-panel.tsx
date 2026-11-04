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
          {rows.length.toLocaleString()} members from the table, across all pages.
        </p>
        <p>Points above the diagonal have a higher (better) PowerFit CC.</p>
      </div>
      <Scatter rows={rows} onSelect={onSelect} metric="cc" />
    </section>
  );
}
