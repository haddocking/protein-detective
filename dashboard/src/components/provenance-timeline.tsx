import { useRef, useState } from "react";
import { defineChart, dot, rect, type ChartInteractionController } from "@tanstack/charts";
import { controlledSignal } from "@tanstack/charts/interaction/signal";
import { zoomX, type ZoomXChange, type ZoomXWindow } from "@tanstack/charts/interaction/zoom";
import { Chart } from "@tanstack/charts/react";
import { scaleBand } from "@tanstack/charts/scales/band";
import { scaleLinear } from "@tanstack/charts/scales/linear";
import { tooltip } from "@tanstack/charts/tooltip";
import { display, provenanceTiming, type Row } from "../data";
import { ChartResetButton } from "./chart-reset-button";
import { PanelHelp } from "./panel-help";

type TimedCommand = NonNullable<ReturnType<typeof provenanceTiming>> & { row: Row; lane: string };

export function ProvenanceTimeline({
  rows,
  onSelect,
}: {
  rows: Row[];
  onSelect: (index: number) => void;
}) {
  const interaction = useRef<ChartInteractionController<TimedCommand, number, string> | null>(null);
  const [zoom, setZoom] = useState<{ extent: string; window: ZoomXWindow<number> } | null>(null);
  const tasks = rows.flatMap((row, index) => {
    const timing = provenanceTiming(row);
    return timing ? [{ ...timing, row, lane: String(index + 1) }] : [];
  });
  if (!tasks.length) return <p className="muted">No complete command timings available.</p>;
  const start = Math.min(...tasks.map((task) => task.start));
  const end = Math.max(...tasks.map((task) => task.end));
  const padding = (end - start || 1000) * 0.02;
  const domain: [number, number] = [start - padding, end + padding];
  const extent = domain.join(":");
  const window = zoom?.extent === extent ? zoom.window : { start: domain[0], end: domain[1] };
  const zoomed = window.start !== domain[0] || window.end !== domain[1];
  const definition = defineChart({
    margin: { top: 12, right: 24, bottom: 64, left: 48 },
    clip: true,
    pointer: false,
    focusRing: false,
    controls: [
      zoomX({
        window: controlledSignal<ZoomXWindow<number>, ZoomXChange<number>>(window, (next) =>
          setZoom({ extent, window: next }),
        ),
        extent: domain,
        scaleExtent: [1, 100],
        wheelActivation: "modifier",
        ariaLabel: "Command timeline zoom and pan",
        ariaDescription:
          "Hold Control or Command and scroll to zoom time; drag to pan. Use plus and minus to zoom, left and right arrows to pan, or Home to reset.",
      }),
    ],
    marks: [
      rect(tasks, {
        key: "lane",
        x1: "start",
        x2: "end",
        y: "lane",
        fill: "#26858c",
        stroke: "#26858c",
        strokeWidth: 2,
        radius: 3,
        states: [{ when: { focus: "primary" }, style: { fill: "#e8a33d", stroke: "#e8a33d" } }],
      }),
      dot(
        tasks.filter((task) => task.start === task.end),
        {
          x: "start",
          y: "lane",
          r: 4,
          fill: "#26858c",
          states: [{ when: { focus: "primary" }, style: { fill: "#e8a33d" } }],
        },
      ),
    ],
    scales: {
      x: {
        scale: scaleLinear().domain([window.start, window.end]),
        grid: true,
        axis: {
          label: "Time (UTC)",
          ticks: {
            count: 5,
            format: (value: number) => new Date(value).toISOString().slice(5, 23).replace("T", " "),
          },
        },
      },
      y: {
        scale: scaleBand()
          .domain(tasks.map((task) => task.lane))
          .padding(0.35),
        axis: {
          ticks: {
            values: tasks.map((task) => task.lane),
          },
        },
      },
    },
    tooltip: {
      use: tooltip,
      content: ([point]) => ({
        title: display(point?.datum.row.command),
        rows: [
          { label: "Start", value: display(point?.datum.row.start_time) },
          { label: "End", value: display(point?.datum.row.end_time) },
          { label: "Duration", value: display(point?.datum.duration) },
        ],
      }),
    },
  });
  return (
    <section aria-labelledby="command-timeline-title">
      <div className="chart-panel-heading">
        <h2 id="command-timeline-title">Command timeline</h2>
        <PanelHelp label="Command timeline controls">
          <p>Ctrl/⌘ + scroll to zoom time; drag to pan.</p>
          <p>Focus the plot and use +/− to zoom, ←/→ to pan, or Home to reset.</p>
          <p>Click command to navigate to its details below.</p>
        </PanelHelp>
      </div>
      <div className="provenance-timeline">
        <div
          className="scatter-plot"
          onPointerMove={(event) => {
            if (!interaction.current) return;
            const target =
              event.buttons === 0 && (event.target as Element).closest("[data-chart-zoom-surface]")
                ? interaction.current.resolvePointer(event.clientX, event.clientY)
                : null;
            interaction.current.setControlledFocus(target, { source: "pointer" });
          }}
          onPointerDown={() => interaction.current?.setControlledFocus(null)}
          onPointerLeave={() => interaction.current?.setControlledFocus(null)}
          onClick={(event) => {
            if (!(event.target as Element).closest("[data-chart-zoom-surface]")) return;
            const target = interaction.current?.resolvePointer(event.clientX, event.clientY);
            if (target) onSelect(Number(target.point.datum.lane) - 1);
          }}
        >
          <ChartResetButton
            onReset={() => setZoom(null)}
            disabled={!zoomed}
            label="Reset command timeline view"
          >
            ↺
          </ChartResetButton>
          <Chart
            definition={definition}
            height={tasks.length * 42 + 76}
            ariaLabel="Command timeline showing each recorded command from start to end in UTC"
            onRender={(context) => {
              interaction.current = context.interaction;
            }}
            onSelect={(point) => {
              if (point) onSelect(Number(point.datum.lane) - 1);
            }}
          />
        </div>
      </div>
      {tasks.length < rows.length && (
        <p className="muted">Commands with missing or invalid timestamps are listed below.</p>
      )}
    </section>
  );
}
