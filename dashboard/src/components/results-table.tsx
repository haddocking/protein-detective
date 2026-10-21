import { display, key, labels, type Dataset, type Row } from "../data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
interface ResultsTableProps {
  items: Row[];
  cols: string[];
  type: Dataset;
  sort?: string;
  desc?: boolean;
}
export function ResultsTable({ items, cols, type, sort, desc = false }: ResultsTableProps) {
  const { navigate, select, selectedId } = useDashboardNavigation();
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>
                {sort ? (
                  <button
                    onClick={() =>
                      navigate({ sort: c, dir: sort === c && desc ? "asc" : "desc", page: "1" })
                    }
                  >
                    {labels[c] ?? c}
                    {sort === c ? (desc ? " ↓" : " ↑") : ""}
                  </button>
                ) : (
                  (labels[c] ?? c)
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((r, i) => (
            <tr
              key={key(r) + "-" + i}
              className={selectedId === key(r) ? "selected" : ""}
              onClick={() => select(r, type)}
            >
              {cols.map((c, j) => (
                <td key={c} className={c === "score_change" && Number(r[c]) < 0 ? "improved" : ""}>
                  {j === 0 ? (
                    <button
                      className="text-link"
                      onClick={(e) => {
                        e.stopPropagation();
                        select(r, type);
                      }}
                    >
                      {display(r[c])}
                    </button>
                  ) : c === "model_available" ? (
                    r[c] ? (
                      "Saved"
                    ) : (
                      "Not saved"
                    )
                  ) : (
                    display(r[c])
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!items.length && <p className="empty">No results match these filters.</p>}
    </div>
  );
}
