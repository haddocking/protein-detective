import { type ReactNode } from "react";
import { display, key, labels, type Row } from "../data";
import type { ResultNavigation } from "../hooks/use-result-navigation";
interface ResultsTableProps {
  items: Row[];
  cols: string[];
  navigation: ResultNavigation;
  sort?: string;
  desc?: boolean;
}
export function ResultsTable({ items, cols, navigation, sort, desc = false }: ResultsTableProps) {
  const { navigate, select, selectedId } = navigation;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {cols.map((c) => {
              let heading: ReactNode = labels[c] ?? c;
              if (sort) {
                let sortIndicator = "";
                if (sort === c) {
                  sortIndicator = " ↑";
                  if (desc) sortIndicator = " ↓";
                }
                let nextDirection = "desc";
                if (sort === c && desc) nextDirection = "asc";
                heading = (
                  <button onClick={() => navigate({ sort: c, dir: nextDirection, page: "1" })}>
                    {labels[c] ?? c}
                    {sortIndicator}
                  </button>
                );
              }
              return <th key={c}>{heading}</th>;
            })}
          </tr>
        </thead>
        <tbody>
          {items.map((r, i) => (
            <tr
              key={key(r) + "-" + i}
              className={selectedId === key(r) ? "selected" : ""}
              onClick={() => select(r)}
            >
              {cols.map((c, j) => {
                let content: ReactNode = display(r[c]);
                if (j === 0) {
                  content = (
                    <button
                      className="text-link"
                      onClick={(e) => {
                        e.stopPropagation();
                        select(r);
                      }}
                    >
                      {display(r[c])}
                    </button>
                  );
                } else if (c === "model_available") {
                  content = "Not saved";
                  if (r[c]) content = "Saved";
                }
                let className = "";
                if (
                  (c === "score_change" && Number(r[c]) < 0) ||
                  (c === "cc_change" && Number(r[c]) > 0)
                )
                  className = "improved";
                return (
                  <td key={c} className={className}>
                    {content}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {!items.length && <p className="empty">No results match these filters.</p>}
    </div>
  );
}
