// @vitest-environment happy-dom
import { createElement, act } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { describe, expect, it, vi } from "vite-plus/test";
import { createDashboardRouter } from "./router";
import { clusterKey } from "./data";

vi.mock("./viewer", () => ({
  StructureViewer: ({
    structureUrl,
    refinedKnownStructureUrl,
  }: {
    structureUrl: string;
    refinedKnownStructureUrl?: string;
  }) =>
    createElement(
      "div",
      { className: "mock-viewer", "data-known-url": refinedKnownStructureUrl },
      structureUrl,
    ),
}));

describe("dashboard routing", () => {
  it("restores result filters and panel selection from existing URLs", async () => {
    const cluster = clusterKey({ refine_run_id: "run 1", structure: "001", cluster_id: 2 });
    const params = new URLSearchParams({
      cluster,
      q: "001",
      top: "all",
      page: "2",
      size: "25",
      sort: "refined_score",
      dir: "asc",
      selected: "member/1",
      selection: "refinements",
      tab: "viewer",
    });
    const router = createDashboardRouter(
      createMemoryHistory({ initialEntries: [`/refinements?${params}`] }),
    );
    await router.load();
    expect(router.state.matches.at(-1)?.routeId).toBe("/refinements");
    expect(router.state.location.search).toEqual(Object.fromEntries(params));
    await router.navigate({
      to: "/refinements",
      search: (previous) => ({ ...previous, page: "3" }),
    });
    await router.load();
    expect(router.state.location.search).toEqual({ ...Object.fromEntries(params), page: "3" });
    expect(new URLSearchParams(router.state.location.searchStr).get("cluster")).toBe(cluster);
  });

  it("keeps deep-link state when clearing the authentication hash", async () => {
    const router = createDashboardRouter(
      createMemoryHistory({
        initialEntries: ["/fitting?q=001&selected=fit-1&tab=viewer#token=secret"],
      }),
    );
    await router.load();
    await router.navigate({ to: ".", search: true, hash: "", replace: true });
    await router.load();
    expect(router.state.location.pathname).toBe("/fitting");
    expect(router.state.location.search).toEqual({ q: "001", selected: "fit-1", tab: "viewer" });
    expect(router.state.location.hash).toBe("");
  });

  it("restores query state through back and forward navigation", async () => {
    const history = createMemoryHistory({ initialEntries: ["/overview?q=protein"] });
    const router = createDashboardRouter(history);
    await router.load();
    await router.navigate({ to: "/provenance", search: {} });
    await router.load();
    expect(router.state.matches.at(-1)?.routeId).toBe("/provenance");
    history.back();
    await router.load();
    expect(router.state.location.pathname).toBe("/overview");
    expect(router.state.location.search).toEqual({ q: "protein" });
    history.forward();
    await router.load();
    expect(router.state.location.pathname).toBe("/provenance");
    expect(router.state.location.search).toEqual({});
  });
});

it("authenticates a direct provenance link and keeps its selected result across pages", async () => {
  const fitting = [
    {
      id: "fit-1",
      candidate_id: "candidate-1",
      structure: "1abc",
      rank: 1,
      cc: 0.8,
      viewer_available: true,
      model_path: "model-1.pdb",
      model_absolute_path: "/session/model-1.pdb",
      density_absolute_path: "/session/density.map",
      density_path: "density.map",
    },
    {
      id: "fit-2",
      candidate_id: "candidate-1",
      structure: "1abc",
      rank: 2,
      cc: 0.7,
      viewer_available: true,
      model_path: "model-2.pdb",
      model_absolute_path: "/session/model-2.pdb",
      density_absolute_path: "/session/density.map",
      density_path: "density.map",
    },
  ];
  const responses: Record<string, unknown> = {
    "/api/auth": {},
    "/api/summary": { fitting_solutions: 1 },
    "/api/provenance": [
      {
        command: "protein-detective powerfit run",
        start_time: "2026-11-04T10:00:00Z",
        end_time: "2026-11-04T10:01:30Z",
      },
      {
        command: "protein-detective powerfit run",
        start_time: "2026-11-04T10:00:30Z",
        end_time: "2026-11-04T10:00:30Z",
      },
      { command: "protein-detective refine", start_time: "2026-11-04T10:01:00Z", end_time: null },
    ],
    "/api/candidates": [{ candidate_id: "candidate-1", structure: "1abc", source: "PDB" }],
    "/api/fitting": fitting,
    "/api/refinements": [
      {
        ...fitting[0],
        id: "refined-1",
        fitted_rank: 2,
        member_rank: 3,
        refine_run_id: "refine-1",
        after_cc: 0.8,
        before_cc: 0.9,
        cc_change: -0.1,
        refined_score: -12,
        baseline_score: -10,
        score_change: -2,
        cluster_score: -11.5,
        cluster_score_std: 0.5,
        fitted_model_absolute_path: "/session/powerfit/unrefined.pdb",
        original_known_structure_absolute_path: "/session/original-known.pdb",
        refined_fitted_structure_absolute_path: "/session/refine/refined-fitted.pdb.gz",
        refined_known_structure: "refine/9_reconstruct/mdref_1_known.pdb.gz",
        refined_known_structure_absolute_path: "/other files/known #1.pdb",
      },
      {
        id: "refined-2",
        structure: "highest-cc",
        viewer_available: true,
        model_path: "highest-cc.pdb",
        density_path: "density.map",
        refined_known_structure: "highest-cc-known.pdb",
        refine_run_id: "refine-2",
        after_cc: 0.95,
        refined_score: 100,
      },
    ],
  };
  const fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(responses[url])));
  vi.stubGlobal("fetch", fetchMock);
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal(
    "navigator",
    Object.create(navigator, {
      clipboard: { value: { writeText } },
    }),
  );
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const router = createDashboardRouter(
    createMemoryHistory({
      initialEntries: [
        "/provenance?selected=fit-1&selection=fitting&tab=details#token=launch-token",
      ],
    }),
  );
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await router.load();
    await act(async () => {
      root.render(createElement(RouterProvider, { router }));
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ token: "launch-token" }) }),
    );
    expect(router.state.location.hash).toBe("");
    expect(router.state.location.search.selected).toBe("fit-1");
    expect(container.querySelector("h1")?.textContent).toBe("Provenance");
    expect(container.querySelector("#command-timeline-title")?.textContent).toBe(
      "Command timeline",
    );
    expect(container.querySelector(".provenance-timeline svg")).not.toBeNull();
    expect(container.querySelectorAll(".provenance")).toHaveLength(3);
    expect(container.querySelectorAll(".provenance")[0]?.textContent).toContain(
      "Duration: 1 min 30 s",
    );
    expect(container.querySelectorAll(".provenance")[1]?.textContent).toContain("Duration: 0 s");
    expect(container.querySelectorAll(".provenance")[2]?.textContent).toContain(
      "Unavailable (missing or invalid timestamps)",
    );
    expect(container.textContent).not.toContain("Hover or focus a command");
    const timeline = container.querySelector(".provenance-timeline")!;
    const reset = timeline.querySelector<HTMLButtonElement>(".chart-reset")!;
    const surface = () => timeline.querySelector("[data-chart-zoom-surface]")!;
    const bar = () => timeline.querySelector('rect[fill="#26858c"]')!;
    const originalWidth = Number(bar().getAttribute("width"));
    const originalY = bar().getAttribute("y");
    expect(reset.disabled).toBe(true);
    await act(async () => {
      surface().dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true }));
    });
    expect(reset.disabled).toBe(false);
    expect(Number(bar().getAttribute("width"))).toBeGreaterThan(originalWidth);
    expect(bar().getAttribute("y")).toBe(originalY);
    const zoomedX = bar().getAttribute("x");
    await act(async () => {
      surface().dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(bar().getAttribute("x")).not.toBe(zoomedX);
    expect(bar().getAttribute("y")).toBe(originalY);
    await act(async () => {
      reset.click();
    });
    expect(reset.disabled).toBe(true);
    expect(Number(bar().getAttribute("width"))).toBe(originalWidth);
    const svg = timeline.querySelector("svg")!;
    const [, , width, height] = svg.getAttribute("viewBox")!.split(" ").map(Number);
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, width, height));
    const marker = timeline.querySelector('circle[fill="#26858c"]')!;
    const targetSection = container.querySelector<HTMLElement>("#command-2")!;
    const scroll = vi.spyOn(targetSection, "scrollIntoView").mockImplementation(() => {});
    await act(async () => {
      surface().dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          clientX: Number(marker.getAttribute("cx")),
          clientY: Number(marker.getAttribute("cy")),
        }),
      );
    });
    expect(targetSection.querySelector("details")?.open).toBe(true);
    expect(container.querySelector("#command-1 details")?.hasAttribute("open")).toBe(false);
    expect(scroll).toHaveBeenCalledWith({ block: "start", behavior: "smooth" });
    expect(document.activeElement).toBe(targetSection);
    expect(container.querySelector("aside h2")?.textContent).toBe("1abc");
    await act(async () => {
      await router.navigate({ to: "/overview", search: true });
    });
    expect(container.querySelector("h1")?.textContent).toBe("Overview");
    expect(container.querySelector("aside h2")?.textContent).toBe("1abc");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/fitting")).toHaveLength(1);

    await act(async () => {
      await router.navigate({
        to: "/overview",
        search: (previous) => ({ ...previous, tab: "viewer" }),
      });
      await vi.dynamicImportSettled();
    });
    expect(container.querySelector<HTMLButtonElement>(".file-paths button")?.title).toBe(
      "/session/model-1.pdb",
    );
    expect(container.querySelectorAll<HTMLButtonElement>(".file-paths button")[1]?.title).toBe(
      "/session/density.map",
    );
    // The overview shows the best refined structure without any clicks.
    expect(container.querySelector(".best-structure .mock-viewer")?.textContent).toBe(
      "/files/highest-cc.pdb",
    );
    expect(container.querySelector(".best-structure h2")?.textContent).toBe(
      "Best refined structure by PowerFit CC score",
    );
    expect(container.querySelector(".best-structure button")?.textContent).toContain(
      "PowerFit CC 0.9500",
    );
    const viewer = container.querySelector("aside .mock-viewer");
    expect(viewer?.textContent).toBe("/files/model-1.pdb");
    const panel = container.querySelector("aside")!;
    expect(panel.style.width).toBe(`${Math.max(440, Math.round(window.innerWidth * 0.6))}px`);
    // Resizing stays under user control until the next entry into the viewer tab.
    await act(async () => {
      container
        .querySelector('[role="separator"]')!
        .dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    const resizedWidth = panel.style.width;
    await act(async () => {
      await router.navigate({
        to: "/overview",
        search: (previous) => ({ ...previous, tab: "details" }),
      });
    });
    expect(container.querySelector("aside .mock-viewer")).toBe(viewer);
    expect(container.querySelector<HTMLElement>(".retained-viewer")?.hidden).toBe(true);
    expect(panel.style.width).toBe(resizedWidth);
    await act(async () => {
      await router.navigate({
        to: "/overview",
        search: (previous) => ({ ...previous, selected: "fit-2", tab: "viewer" }),
      });
    });
    expect(container.querySelector("aside .mock-viewer")).toBe(viewer);
    expect(viewer?.textContent).toBe("/files/model-2.pdb");
    expect(container.querySelector<HTMLButtonElement>(".file-paths button")?.title).toBe(
      "/session/model-2.pdb",
    );
    expect(container.querySelector<HTMLElement>(".retained-viewer")?.hidden).toBe(false);
    expect(panel.style.width).toBe(`${Math.max(440, Math.round(window.innerWidth * 0.6))}px`);
    await act(async () => {
      await router.navigate({ to: "/overview", search: {} });
    });
    expect(container.querySelector("aside")).toBeNull();
    await act(async () => {
      await router.navigate({
        to: "/overview",
        search: { selected: "fit-1", selection: "fitting", tab: "details" },
      });
    });
    expect(container.querySelector("aside .mock-viewer")).toBeNull();
    expect(container.querySelector("aside h2")?.textContent).toBe("1abc");
    await act(async () => {
      await router.navigate({
        to: "/refinements",
        search: { selected: "refined-1", selection: "refinements", tab: "details" },
      });
    });
    expect(container.querySelector(".filter-summary")?.textContent).toBe(
      '(active filter: "Best HADDOCK score")',
    );
    expect(container.querySelector<HTMLDetailsElement>(".result-filters")?.open).toBe(false);
    const helpButtons = container.querySelectorAll<HTMLButtonElement>("main .panel-help > button");
    expect(helpButtons).toHaveLength(3);
    for (const button of helpButtons) {
      const popover = button.nextElementSibling!;
      expect(button.getAttribute("popovertarget")).toBe(popover.id);
      expect(popover.getAttribute("popover")).toBe("auto");
      expect(button.getAttribute("aria-label")).toContain("controls");
    }
    expect(container.querySelector(".results-section .section-heading kbd")).toBeNull();
    expect(container.querySelector(".results-section .panel-help-content")?.textContent).toContain(
      "step through members",
    );
    const comparisons = container.querySelectorAll(".comparison-charts section");
    expect(Array.from(comparisons, (panel) => panel.querySelector("h2")?.textContent)).toEqual([
      "HADDOCK score comparison",
      "PowerFit CC comparison",
    ]);
    for (const [index, metric] of ["HADDOCK score", "PowerFit CC"].entries()) {
      expect(
        comparisons[index]?.querySelector(
          `[aria-label="${metric} before versus after refinement"]`,
        ),
      ).not.toBeNull();
      expect(comparisons[index]?.textContent).toContain(`${metric} before refinement`);
      expect(comparisons[index]?.textContent).toContain(`${metric} after refinement`);
      const zoomSurface = comparisons[index]!.querySelector<SVGElement>(
        `[aria-label="${metric} zoom and pan"]`,
      )!;
      const reset = comparisons[index]!.querySelector<HTMLButtonElement>(".chart-reset")!;
      const plot = comparisons[index]!.querySelector(".scatter-plot")!;
      const originalAxes = plot.textContent;
      const point = plot.querySelector("circle")!;
      const originalPointX = point.getAttribute("cx");
      const originalPointY = point.getAttribute("cy");
      expect(reset.disabled).toBe(true);
      await act(async () => {
        zoomSurface.dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true }));
      });
      expect(reset.disabled).toBe(false);
      expect(plot.textContent).not.toBe(originalAxes);
      expect(point.getAttribute("cx")).not.toBe(originalPointX);
      expect(point.getAttribute("cy")).not.toBe(originalPointY);
      const zoomedX = point.getAttribute("cx");
      const zoomedY = point.getAttribute("cy");
      await act(async () => {
        zoomSurface.dispatchEvent(
          new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
        );
      });
      expect(point.getAttribute("cx")).not.toBe(zoomedX);
      expect(point.getAttribute("cy")).not.toBe(zoomedY);
      await act(async () => reset.click());
      expect(reset.disabled).toBe(true);
      expect(point.getAttribute("cx")).toBe(originalPointX);
      expect(point.getAttribute("cy")).toBe(originalPointY);
      expect(plot.textContent).toBe(originalAxes);
      const svg = point.ownerSVGElement!;
      const [, , width, height] = svg.getAttribute("viewBox")!.split(" ").map(Number);
      const bounds = vi
        .spyOn(svg, "getBoundingClientRect")
        .mockReturnValue(new DOMRect(0, 0, width, height));
      await act(async () => {
        zoomSurface.dispatchEvent(
          new PointerEvent("pointermove", {
            bubbles: true,
            clientX: Number(originalPointX),
            clientY: Number(originalPointY),
          }),
        );
      });
      const tooltip = plot.querySelector<HTMLElement>('[role="status"]')!;
      expect(tooltip.hidden).toBe(false);
      expect(tooltip.textContent).not.toContain("Structure");
      expect(tooltip.textContent).toContain("1abc");
      expect(tooltip.textContent).toContain("Fitted rank2");
      expect(tooltip.textContent).toContain("HADDOCK member rank3");
      expect(tooltip.textContent).toContain("Before");
      expect(tooltip.textContent).toContain("After");
      const expectedChange = ["-2", "-0.1000"][index];
      expect(tooltip.textContent).toContain(`Change${expectedChange}`);
      const expectedValues = [
        ["-10", "-12"],
        ["0.9000", "0.8000"],
      ][index]!;
      for (const value of expectedValues) expect(tooltip.textContent).toContain(value);
      await act(async () => {
        zoomSurface.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, buttons: 1 }));
      });
      expect(tooltip.hidden).toBe(true);
      bounds.mockRestore();
    }
    expect(container.querySelector("main tbody tr")?.textContent).toContain("highest-cc");
    expect(container.querySelector("main thead")?.textContent).toContain(
      "PowerFit CC after refinement ↓",
    );
    expect(container.querySelector("main thead")?.textContent).toContain(
      "PowerFit CC change (after − before)",
    );
    expect(container.querySelector("main thead")?.textContent).toContain(
      "HADDOCK score change (after − before)",
    );
    const detailLabels = Array.from(container.querySelectorAll("aside dt"), (dt) => dt.textContent);
    const scoreIndex = detailLabels.indexOf("HADDOCK score after refinement");
    expect(scoreIndex).toBeGreaterThan(0);
    expect(detailLabels[scoreIndex - 1]).toBe("PowerFit CC after refinement");
    expect(detailLabels.slice(-6)).toEqual([
      "PowerFit CC before refinement",
      "PowerFit CC change (after − before)",
      "HADDOCK score before refinement",
      "HADDOCK score change (after − before)",
      "HADDOCK cluster score",
      "HADDOCK cluster score standard deviation",
    ]);
    await act(async () => {
      await router.navigate({
        to: "/refinements",
        search: { selected: "refined-1", selection: "refinements" },
      });
      await vi.dynamicImportSettled();
    });
    expect(container.querySelector<HTMLElement>(".retained-viewer")?.hidden).toBe(false);
    // Selecting a related result also opens the viewer by default.
    expect(container.querySelector("aside .mock-viewer")?.getAttribute("data-known-url")).toBe(
      "/files/refine/9_reconstruct/mdref_1_known.pdb.gz",
    );
    await act(async () => {
      await router.navigate({
        to: "/refinements",
        search: { selected: "refined-1", selection: "refinements", tab: "details" },
      });
    });
    await act(async () => container.querySelector<HTMLButtonElement>("button.related")!.click());
    expect(router.state.location.search.tab).toBe("viewer");
    await act(async () => {
      await router.navigate({
        to: "/refinements",
        search: { selected: "refined-1", selection: "refinements", tab: "details" },
      });
    });
    const fileTrigger = container.querySelector<HTMLButtonElement>(".file-menu > button")!;
    const fileMenu = container.querySelector<HTMLElement>(".file-menu-content")!;
    expect(fileTrigger.getAttribute("popovertarget")).toBe(fileMenu.id);
    expect(fileMenu.getAttribute("popover")).toBe("auto");
    vi.spyOn(fileTrigger, "getBoundingClientRect").mockReturnValue(new DOMRect(800, 100, 80, 32));
    await act(async () => {
      fileMenu.dispatchEvent(Object.assign(new Event("beforetoggle"), { newState: "open" }));
    });
    expect(fileMenu.style.getPropertyValue("--file-menu-top")).toBe("132px");
    expect(fileMenu.style.getPropertyValue("--file-menu-right")).toBe(
      `${window.innerWidth - 880}px`,
    );
    const copyButtons = container.querySelectorAll<HTMLButtonElement>(".file-paths button");
    const inputButtons = container.querySelectorAll<HTMLButtonElement>(
      '[aria-label="Inputs"] button',
    );
    expect(
      Array.from(inputButtons, (button) => [button.getAttribute("aria-label"), button.title]),
    ).toEqual([
      ["Copy density path", "/session/density.map"],
      ["Copy unrefined fitted model path", "/session/powerfit/unrefined.pdb"],
      ["Copy original known structure path", "/session/original-known.pdb"],
    ]);
    const outputButtons = container.querySelectorAll<HTMLButtonElement>(
      '[aria-label="Outputs"] button',
    );
    expect(
      Array.from(outputButtons, (button) => [button.getAttribute("aria-label"), button.title]),
    ).toEqual([
      ["Copy refined fitted structure path", "/session/refine/refined-fitted.pdb.gz"],
      ["Copy refined known structure path", "/other files/known #1.pdb"],
    ]);
    for (const button of copyButtons) {
      await act(async () => button.click());
      expect(writeText).toHaveBeenLastCalledWith(button.title);
      expect(button.querySelector('[role="status"]')?.textContent).toBe("Copied");
    }
    writeText.mockRejectedValueOnce(new Error("Clipboard denied"));
    await act(async () => copyButtons[0].click());
    expect(copyButtons[0].querySelector('[role="status"]')?.textContent).toBe("Copy failed");
    // Opening a results page shows its first result in the viewer.
    await act(async () => {
      await router.navigate({ to: "/fitting", search: {} });
    });
    expect(router.state.location.search).toEqual({
      selected: "fit-1",
      selection: "fitting",
      tab: "viewer",
    });
    // Keyboard navigation steps through solutions and stops at the ends.
    await act(async () => {
      await router.navigate({ to: "/fitting", search: { top: "all" } });
    });
    expect(container.querySelector(".filter-summary")?.textContent).toBe("(no active filters)");
    const press = (key: string) =>
      act(async () => {
        dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
      });
    await press("j");
    expect(router.state.location.search.selected).toBe("fit-1");
    await press("ArrowDown");
    expect(router.state.location.search.selected).toBe("fit-2");
    await press("j");
    expect(router.state.location.search.selected).toBe("fit-2");
    await press("k");
    expect(router.state.location.search).toMatchObject({ selected: "fit-1", tab: "viewer" });
    await act(async () => {
      await router.navigate({
        to: "/refinements",
        search: { top: "3", q: "1abc", source: "PDB", refine_run_id: "refine-1" },
      });
    });
    const activeFilters = container.querySelector(".filter-summary")!;
    expect(activeFilters.textContent).toBe(
      '(active filters: "Top 3", Search: "1abc", Source: "PDB", Refinement run: "refine-1")',
    );
    expect(activeFilters.getAttribute("title")).toBe(activeFilters.textContent);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/auth")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/summary")).toHaveLength(1);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});

it("charts use the table's top-N results across all pages", async () => {
  const rows = Array.from({ length: 60 }, (_, i) => ({
    id: `row-${i}`,
    candidate_id: `structure-${Math.floor(i / 2)}`,
    structure: `structure-${Math.floor(i / 2)}`,
    powerfit_run_id: "fit",
    refine_run_id: "refine",
    fitted_rank: 1,
    cluster_id: 1,
    rank: (i % 2) + 1,
    member_rank: (i % 2) + 1,
    cc: 0.1 + i / 1000,
    before_cc: 0.1 + i / 1000,
    after_cc: 0.2 + i / 1000,
    baseline_score: -i,
    refined_score: -i - 10,
  }));
  const responses: Record<string, unknown> = {
    "/api/auth": {},
    "/api/summary": { fitted_structures: 60 },
    "/api/candidates": [],
    "/api/fitting": rows,
    "/api/refinements": rows,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => new Response(JSON.stringify(responses[url]))),
  );
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const router = createDashboardRouter(createMemoryHistory({ initialEntries: ["/fitting"] }));
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await router.load();
    await act(async () => root.render(createElement(RouterProvider, { router })));
    for (const view of ["fitting", "refinements"] as const) {
      for (const [top, page, tableCount, chartCount] of [
        ["1", "1", 25, 30],
        ["1", "2", 5, 30],
        ["all", "1", 25, 60],
      ] as const) {
        await act(async () => {
          await router.navigate({
            to: `/${view}`,
            search: { top, page, size: "25", selected: "row-0", selection: view, tab: "details" },
          });
        });
        expect(container.querySelectorAll(".results-section tbody tr")).toHaveLength(tableCount);
        for (const panel of container.querySelectorAll(".chart-section")) {
          expect(panel.querySelector(".muted")?.textContent).toContain(
            `${chartCount} ${view === "fitting" ? "solutions" : "members"} from the table, across all pages.`,
          );
          if (view === "refinements") {
            expect(panel.querySelectorAll('circle[fill="#26858c"]')).toHaveLength(chartCount);
            const highlight = panel.querySelectorAll('circle[fill="#e8a33d"]');
            expect(highlight).toHaveLength(1);
            expect(highlight[0].getAttribute("r")).toBe("5");
          }
          if (view === "fitting") {
            const heading = panel.querySelector(".chart-panel-heading")!;
            expect(heading.querySelector("h2")?.textContent).toBe("PowerFit score distribution");
            const help = heading.querySelector<HTMLButtonElement>(".panel-help > button")!;
            expect(help.getAttribute("aria-label")).toBe("Histogram controls");
            expect(help.getAttribute("popovertarget")).toBe(help.nextElementSibling?.id);
            expect(panel.querySelector(".ts-chart-host .panel-help")).toBeNull();
          }
        }
      }
    }
    const highlightPositions = () =>
      Array.from(container.querySelectorAll('.chart-section circle[fill="#e8a33d"]')).map(
        (point) => [point.getAttribute("cx"), point.getAttribute("cy")],
      );
    const previous = highlightPositions();
    expect(previous).toHaveLength(2);
    await act(async () => {
      container.querySelector<HTMLButtonElement>("tbody tr:nth-child(2) button")!.click();
    });
    const next = highlightPositions();
    expect(next).toHaveLength(2);
    next.forEach((position, i) => expect(position).not.toEqual(previous[i]));
    await act(async () => {
      await router.navigate({ to: "/refinements", search: { top: "all" } });
    });
    expect(highlightPositions()).toHaveLength(0);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});
