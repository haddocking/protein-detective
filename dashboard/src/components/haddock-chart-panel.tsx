import { Scatter } from "../charts";
import { type Row } from "../data";

export function HaddockChartPanel({
  rows,
  onSelect,
}: {
  rows: Row[];
  onSelect: (row: Row) => void;
}) {
  return (
    <section className="chart-section">
      <div>
        <h2>HADDOCK score comparison</h2>
        <p className="muted">
          All {rows.length.toLocaleString()} matching members, before top-N selection and
          pagination.
        </p>
        <p>Points below the diagonal have a lower (better) HADDOCK score.</p>
      </div>
      <Scatter rows={rows} onSelect={onSelect} metric="haddock" />
    </section>
  );
}
