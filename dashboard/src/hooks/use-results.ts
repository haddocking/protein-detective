import { useState } from "react";
import {
  csv,
  filterRows,
  fittingColumns,
  refinementColumns,
  grouped,
  sorted,
  topSelection,
  tablePageSize,
  positivePage,
  key,
  type Row,
} from "../data";
import { type ResultKind } from "../navigation";
import { useSession } from "./use-session-data";
import { useDashboardNavigation } from "./use-dashboard-navigation";
export function useResults(kind: ResultKind) {
  const { data } = useSession();
  const { p, navigate } = useDashboardNavigation();
  const [notice, setNotice] = useState("");
  const rows = data[kind] ?? [];
  const filtered = filterRows(rows, p);
  const columns = kind === "fitting" ? fittingColumns : refinementColumns;
  const sort = columns.includes(p.get("sort") ?? "")
    ? p.get("sort")!
    : kind === "fitting"
      ? "cc"
      : "refined_score";
  const desc = p.get("dir") ? p.get("dir") === "desc" : kind === "fitting";
  const limit = topSelection(p.get("top"));
  const selectedRows = sorted(grouped(filtered, kind, limit), sort, desc);
  const pageSize = tablePageSize(p.get("size"));
  const page = Math.min(
    positivePage(p.get("page")),
    Math.max(1, Math.ceil(selectedRows.length / pageSize)),
  );
  function exportCsv() {
    const blob = new Blob([csv(selectedRows, columns)], { type: "text/csv;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `protein-detective-${kind}.csv`;
    a.click();
    URL.revokeObjectURL(href);
  }
  function chartSelect(row: Row) {
    const included = selectedRows.some((r) => key(r) === key(row));
    const all = sorted(grouped(filtered, kind, included ? limit : "all"), sort, desc);
    if (!included) setNotice("Switched to All members to reveal the selected chart point.");
    navigate({
      selected: key(row),
      selection: "refinements",
      tab: row.viewer_available ? "viewer" : "details",
      top: included ? limit : "all",
      page: String(Math.floor(all.findIndex((r) => key(r) === key(row)) / pageSize) + 1),
    });
  }
  return {
    rows,
    filtered,
    columns,
    sort,
    desc,
    limit,
    selectedRows,
    pageSize,
    page,
    notice,
    setNotice,
    exportCsv,
    chartSelect,
  };
}
