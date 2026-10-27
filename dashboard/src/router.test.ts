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
    "/api/provenance": [],
    "/api/candidates": [{ candidate_id: "candidate-1", structure: "1abc", source: "PDB" }],
    "/api/fitting": fitting,
    "/api/refinements": [
      {
        ...fitting[0],
        id: "refined-1",
        refine_run_id: "refine-1",
        after_cc: 0.8,
        refined_score: -12,
        fitted_model_absolute_path: "/session/powerfit/unrefined.pdb",
        original_known_structure_absolute_path: "/session/original-known.pdb",
        refined_fitted_structure_absolute_path: "/session/refine/refined-fitted.pdb.gz",
        refined_known_structure: "refine/9_reconstruct/mdref_1_known.pdb.gz",
        refined_known_structure_absolute_path: "/other files/known #1.pdb",
      },
      {
        id: "refined-2",
        structure: "highest-cc",
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
      "/files/model-1.pdb",
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
    expect(container.querySelector("main tbody tr")?.textContent).toContain("highest-cc");
    expect(container.querySelector("main thead")?.textContent).toContain(
      "PowerFit CC after refinement ↓",
    );
    expect(container.querySelector("main thead")?.textContent).toContain(
      "PowerFit CC change (after − before)",
    );
    expect(container.querySelector("main thead")?.textContent).toContain(
      "CAPRI score change (after − before)",
    );
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
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/auth")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/summary")).toHaveLength(1);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});
