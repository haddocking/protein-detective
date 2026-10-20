import { datasetsForView, positivePage, tablePageSize, topSelection } from "./data";
import { describe, it, expect } from "vite-plus/test";
import { csv, filterRows, grouped, histogram, sorted } from "./data";

describe("snapshot result operations", () => {
  it("keeps structure identity and PowerFit runs separate", () => {
    const rows = [
      { structure: "a", powerfit_run_id: "r1", rank: 2 },
      { structure: "a", powerfit_run_id: "r1", rank: 1 },
      { structure: "a", powerfit_run_id: "r2", rank: 1 },
      { structure: "b", powerfit_run_id: "r1", rank: 1 },
    ];
    expect(grouped(rows, "fitting", "1")).toEqual([rows[1], rows[2], rows[3]]);
    expect(grouped(rows, "fitting", "all")).toHaveLength(4);
  });
  it("keeps refinement runs, inputs and clusters separate", () => {
    const rows = [
      { structure: "a", refine_run_id: "r1", fitted_rank: 1, cluster_id: 1, member_rank: 2 },
      { structure: "a", refine_run_id: "r1", fitted_rank: 1, cluster_id: 1, member_rank: 1 },
      { structure: "a", refine_run_id: "r2", fitted_rank: 1, cluster_id: 1, member_rank: 1 },
      { structure: "a", refine_run_id: "r1", fitted_rank: 2, cluster_id: 1, member_rank: 1 },
    ];
    expect(grouped(rows, "refinements", "1")).toEqual([rows[1], rows[2], rows[3]]);
  });
  it("filters before grouping and exports all sorted rows with table columns", () => {
    const rows = Array.from({ length: 110 }, (_, i) => ({
      structure: `a,${i}`,
      source: "PDB",
      powerfit_run_id: "r",
      rank: i + 1,
      cc: i,
    }));
    const filtered = filterRows(rows, new URLSearchParams("source=PDB&q=a"));
    const ordered = sorted(grouped(filtered, "fitting", "all"), "cc", true);
    const result = csv(ordered, ["structure", "cc"]);
    expect(result.split("\r\n")).toHaveLength(111);
    expect(result.split("\r\n")[1]).toBe('"a,109","109"');
    expect(result.startsWith('"Structure","CC"')).toBe(true);
  });
  it("bins every finite score including maximum and retains chart scope", () => {
    const rows = [{ cc: 0 }, { cc: 1 }, { cc: 0.5 }, { cc: null }];
    expect(histogram(rows, "cc").reduce((a, b) => a + b.count, 0)).toBe(3);
    expect(histogram(rows, "cc")[19].count).toBe(1);
  });
});

it("keeps different fitted input paths separate when ranks repeat", () => {
  const rows = [
    { structure: "a", refine_run_id: "r", fitted_model: "input-a", cluster_id: 1, member_rank: 1 },
    { structure: "a", refine_run_id: "r", fitted_model: "input-b", cluster_id: 1, member_rank: 1 },
  ];
  expect(grouped(rows, "refinements", "1")).toHaveLength(2);
});

it("loads selected and related datasets on direct provenance URLs", () => {
  expect(datasetsForView("provenance", "selected-fit")).toEqual([
    "provenance",
    "candidates",
    "fitting",
    "refinements",
  ]);
  expect(datasetsForView("refinements", "selected-fit")).toContain("fitting");
  expect(datasetsForView("fitting", "selected-refinement")).toContain("refinements");
  expect(datasetsForView("provenance", null)).toEqual(["provenance"]);
});
it("normalizes malformed URL table settings", () => {
  for (const value of ["-1", "Infinity", "NaN", "2.5", "0", "1e99"])
    expect(positivePage(value)).toBe(1);
  expect(positivePage("3")).toBe(3);
  for (const value of ["-1", "0", "51", "Infinity"]) expect(tablePageSize(value)).toBe(50);
  expect(tablePageSize("100")).toBe(100);
  expect(topSelection("Infinity")).toBe("1");
  expect(topSelection("all")).toBe("all");
});
