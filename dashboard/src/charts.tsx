import { useMemo } from "react";
import { barY, defineChart, dot, lineY } from "@tanstack/charts";
import { Chart } from "@tanstack/charts/react";
import { scaleBand } from "@tanstack/charts/scales/band";
import { scaleLinear } from "@tanstack/charts/scales/linear";
import { tooltip } from "@tanstack/charts/tooltip";
import { histogram, type Row } from "./data";
export function Histogram({ rows, metric }: { rows: Row[]; metric: string }) {
  const definition = useMemo(() => {
    const bins = histogram(rows, metric).map((b) => ({
      ...b,
      range: `${b.start.toFixed(3)} – ${b.end.toFixed(3)}`,
    }));
    return defineChart({
      marks: [barY(bins, { x: "range", y: "count", fill: "#26858c" })],
      scales: {
        x: { scale: () => scaleBand().padding(0.1), axis: { label: metric, ticks: { count: 4 } } },
        y: { scale: scaleLinear, axis: { label: "Solutions" }, grid: true },
      },
      tooltip,
    });
  }, [rows, metric]);
  return (
    <Chart
      definition={definition}
      height={225}
      ariaLabel={`${metric} histogram of all filtered solutions; tooltip shows score range and count`}
    />
  );
}
export function Scatter({ rows, onSelect }: { rows: Row[]; onSelect: (r: Row) => void }) {
  const definition = useMemo(() => {
    const data = rows
      .filter((r) => typeof r.baseline_score === "number" && typeof r.refined_score === "number")
      .map((r) => ({ ...r, x: Number(r.baseline_score), y: Number(r.refined_score) }));
    const values = data.flatMap((r) => [r.x, r.y]);
    const lo = values.length ? Math.min(...values) : 0,
      hi = values.length ? Math.max(...values) : 1;
    const domain: [number, number] = [lo - (hi - lo || 1) * 0.05, hi + (hi - lo || 1) * 0.05];
    return defineChart({
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
          axis: { label: "Baseline score" },
          grid: true,
        },
        y: {
          scale: () => scaleLinear().domain(domain),
          axis: { label: "Refined score" },
          grid: true,
        },
      },
      tooltip,
    });
  }, [rows]);
  return (
    <div className="scatter">
      <Chart
        definition={definition}
        aspectRatio={1}
        initialWidth={300}
        ariaLabel="Baseline versus refined score, equal axis scales"
        onSelect={(point) => {
          if (point && "id" in point.datum) onSelect(point.datum);
        }}
      />
    </div>
  );
}
