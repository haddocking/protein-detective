import { barY, defineChart, dot, lineY } from "@tanstack/charts";
import { Chart } from "@tanstack/charts/react";
import { scaleBand } from "@tanstack/charts/scales/band";
import { scaleLinear } from "@tanstack/charts/scales/linear";
import { tooltip } from "@tanstack/charts/tooltip";
import { histogram, labels, type Row } from "./data";

export function Histogram({ rows, metric }: { rows: Row[]; metric: string }) {
  const bins = histogram(rows, metric).map((b) => ({
    ...b,
    range: `${b.start.toFixed(3)} – ${b.end.toFixed(3)}`,
  }));
  const definition = defineChart({
    marks: [barY(bins, { x: "range", y: "count", fill: "#26858c" })],
    scales: {
      x: {
        scale: () => scaleBand().padding(0.1),
        axis: { label: labels[metric] ?? metric, ticks: { count: 4 } },
      },
      y: { scale: scaleLinear, axis: { label: "Solutions" }, grid: true },
    },
    tooltip,
  });
  return (
    <Chart
      definition={definition}
      height={225}
      ariaLabel={`${labels[metric] ?? metric} histogram of all filtered solutions; tooltip shows score range and count`}
    />
  );
}

export function Scatter({ rows, onSelect }: { rows: Row[]; onSelect: (r: Row) => void }) {
  const data = rows
    .filter((r) => typeof r.baseline_score === "number" && typeof r.refined_score === "number")
    .map((r) => ({ ...r, x: Number(r.baseline_score), y: Number(r.refined_score) }));
  const values = data.flatMap((r) => [r.x, r.y]);
  const lo = values.length ? Math.min(...values) : 0,
    hi = values.length ? Math.max(...values) : 1;
  const domain: [number, number] = [lo - (hi - lo || 1) * 0.05, hi + (hi - lo || 1) * 0.05];
  const definition = defineChart({
    margin: 60,
    marks: [
      lineY(
        [
          { x: domain[0], y: domain[0] },
          { x: domain[1], y: domain[1] },
        ],
        { x: "x", y: "y", stroke: "#8e979e" },
      ),
      dot(data, { x: "x", y: "y", r: 5, fill: "#26858c", key: (r) => String((r as Row).id) }),
    ],
    scales: {
      x: {
        scale: () => scaleLinear().domain(domain),
        axis: { label: "CAPRI score before refinement" },
        grid: true,
      },
      y: {
        scale: () => scaleLinear().domain(domain),
        axis: { label: "CAPRI score after refinement" },
        grid: true,
      },
    },
    tooltip,
  });
  return (
    <div className="scatter">
      <Chart
        definition={definition}
        aspectRatio={1}
        initialWidth={300}
        ariaLabel="CAPRI score before versus after refinement, equal axis scales"
        onSelect={(point) => {
          if (point && "id" in point.datum) onSelect(point.datum);
        }}
      />
    </div>
  );
}
