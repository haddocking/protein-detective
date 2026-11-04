import { type Row } from "../data";
export function EmptyResults({ summary }: { summary: Row }) {
  if (summary.fitting_status === "no_runs" || !summary.fitting_solutions)
    return (
      <div className="empty">
        <h3>
          {summary.fitting_status === "incomplete"
            ? "Fitting is incomplete or results are missing."
            : "No fitting solutions yet"}
        </h3>
        <p>Run PowerFit to compare candidate structures with your density map.</p>
        <code>protein-detective powerfit run TARGET_MAP RESOLUTION SESSION_DIR</code>
      </div>
    );
  return (
    <div className="empty">
      <h3>No refinement results</h3>
      <p>Available candidates and fitting results remain accessible.</p>
    </div>
  );
}
