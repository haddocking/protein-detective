import { useRef, useState } from "react";
import { controlledSignal } from "@tanstack/charts/interaction/signal";
import { zoomX, type ZoomXChange, type ZoomXWindow } from "@tanstack/charts/interaction/zoom";
import { barY, defineChart, dot, lineY, type ChartInteractionController } from "@tanstack/charts";
import { Chart } from "@tanstack/charts/react";
import { scaleBand } from "@tanstack/charts/scales/band";
import { scaleLinear } from "@tanstack/charts/scales/linear";
import { tooltip } from "@tanstack/charts/tooltip";
import { PanelHelp } from "./components/panel-help";
import { display, histogram, labels, type Row } from "./data";

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

type ScatterPoint = Row & { x: number; y: number };

export function Scatter({
  rows,
  onSelect,
  metric = "haddock",
}: {
  rows: Row[];
  onSelect: (r: Row) => void;
  metric?: "haddock" | "cc";
}) {
  const interaction = useRef<ChartInteractionController<ScatterPoint, number, number> | null>(null);
  const [zoom, setZoom] = useState<{
    extent: string;
    window: ZoomXWindow<number>;
  } | null>(null);
  const before = metric === "cc" ? "before_cc" : "baseline_score";
  const after = metric === "cc" ? "after_cc" : "refined_score";
  const title = metric === "cc" ? "PowerFit CC" : "HADDOCK score";
  const data = rows
    .filter((r) => typeof r[before] === "number" && typeof r[after] === "number")
    .map((r): ScatterPoint => ({ ...r, x: Number(r[before]), y: Number(r[after]) }));
  const values = data.flatMap((r) => [r.x, r.y]);
  const lo = values.length ? Math.min(...values) : 0,
    hi = values.length ? Math.max(...values) : 1;
  const domain: [number, number] = [lo - (hi - lo || 1) * 0.05, hi + (hi - lo || 1) * 0.05];
  const diagonal: ScatterPoint[] = [
    { x: domain[0], y: domain[0] },
    { x: domain[1], y: domain[1] },
  ];
  const extent = `${metric}:${domain.join(",")}`;
  let window: ZoomXWindow<number> = { start: domain[0], end: domain[1] };
  if (zoom?.extent === extent) window = zoom.window;
  const zoomed = window.start !== domain[0] || window.end !== domain[1];
  const definition = defineChart({
    margin: { top: 12, right: 12, bottom: 48, left: 48 },
    clip: true,
    pointer: false,
    controls: [
      zoomX({
        window: controlledSignal<ZoomXWindow<number>, ZoomXChange<number>>(window, (next) =>
          setZoom({ extent, window: next }),
        ),
        extent: domain,
        scaleExtent: [1, 100],
        wheelActivation: "modifier",
        ariaLabel: `${title} zoom and pan`,
        ariaDescription:
          "Zoom and pan both axes together. Hold Control or Command and scroll to zoom; drag to pan. Use plus and minus to zoom, left and right arrows to pan, or Home to reset.",
      }),
    ],
    marks: [
      lineY(diagonal, { x: (r) => r.x, y: (r) => r.y, stroke: "#8e979e" }),
      dot(data, { x: (r) => r.x, y: (r) => r.y, r: 5, fill: "#26858c", key: (r) => String(r.id) }),
    ],
    scales: {
      x: {
        scale: scaleLinear().domain([window.start, window.end]),
        axis: {
          label: { text: `${title} before refinement`, fontSize: 11 },
          tickLabels: { fontSize: 10 },
        },
        grid: true,
      },
      y: {
        scale: scaleLinear().domain([window.start, window.end]),
        axis: {
          label: { text: `${title} after refinement`, fontSize: 11 },
          tickLabels: { fontSize: 10 },
        },
        grid: true,
      },
    },
    tooltip: {
      use: tooltip,
      content: ([point]) => ({
        title: display(point?.datum.structure),
        rows: [
          { label: "Fitted rank", value: display(point?.datum.fitted_rank) },
          { label: "HADDOCK member rank", value: display(point?.datum.member_rank) },
          { label: "Before", value: display(point?.xValue) },
          { label: "After", value: display(point?.yValue) },
          {
            label: "Change",
            value: display(point && point.yValue - point.xValue),
          },
        ],
      }),
    },
  });
  return (
    <div className="scatter">
      <PanelHelp label={`${title} chart controls`}>
        <p>Ctrl/⌘ + scroll to zoom both axes together; drag to pan.</p>
        <p>
          Focus the plot and use <kbd>+</kbd>/<kbd>−</kbd> to zoom,
          <kbd>←</kbd>/<kbd>→</kbd> to pan, or <kbd>Home</kbd> to reset.
        </p>
        <p>Select a point to inspect its result. Use the reset icon to restore the full view.</p>
      </PanelHelp>
      <div
        className="scatter-plot"
        onPointerMove={(event) => {
          const controller = interaction.current;
          if (!controller) return;
          let target = null;
          if (
            event.buttons === 0 &&
            (event.target as Element).closest("[data-chart-zoom-surface]")
          ) {
            target = controller.resolvePointer(event.clientX, event.clientY);
            if (!target?.point.datum.structure) target = null;
          }
          controller.setControlledFocus(target, { source: "pointer" });
        }}
        onPointerDown={() => interaction.current?.setControlledFocus(null)}
        onPointerLeave={() => interaction.current?.setControlledFocus(null)}
        onClick={(event) => {
          if (!(event.target as Element).closest("[data-chart-zoom-surface]")) return;
          const target = interaction.current?.resolvePointer(event.clientX, event.clientY);
          if (target && "id" in target.point.datum) onSelect(target.point.datum);
        }}
      >
        <button
          className="chart-reset"
          onClick={() => setZoom(null)}
          disabled={!zoomed}
          aria-label="Reset chart view"
          title="Reset view"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 6v3l4-4-4-4v3c-4.42 0-8 3.58-8 8 0 1.57.46 3.03 1.24 4.26L6.7 14.8c-.45-.83-.7-1.79-.7-2.8 0-3.31 2.69-6 6-6zm6.76 1.74L17.3 9.2c.44.84.7 1.79.7 2.8 0 3.31-2.69 6-6 6v-3l-4 4 4 4v-3c4.42 0 8-3.58 8-8 0-1.57-.46-3.03-1.24-4.26z" />
          </svg>
        </button>
        <Chart
          definition={definition}
          aspectRatio={1}
          initialWidth={300}
          ariaLabel={`${title} before versus after refinement`}
          onRender={(context) => {
            interaction.current = context.interaction;
          }}
          onSelect={(point) => {
            if (point && "id" in point.datum) onSelect(point.datum);
          }}
        />
      </div>
    </div>
  );
}
