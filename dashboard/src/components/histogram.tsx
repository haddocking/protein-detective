import { barY, defineChart } from "@tanstack/charts";
import { Chart } from "@tanstack/charts/react";
import { scaleBand } from "@tanstack/charts/scales/band";
import { scaleLinear } from "@tanstack/charts/scales/linear";
import { tooltip } from "@tanstack/charts/tooltip";
import { histogram, labels, type Row } from "../data";

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
