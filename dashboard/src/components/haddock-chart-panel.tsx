import { RefineScatter } from "./refine-scatter";
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
          {rows.length.toLocaleString()} members from the table, across all pages.
        </p>
        <p>Points below the diagonal have a lower (better) HADDOCK score.</p>
      </div>
      <RefineScatter rows={rows} onSelect={onSelect} />
    </section>
  );
}
