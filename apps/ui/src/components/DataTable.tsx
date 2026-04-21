import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: string;
  render: (item: T) => ReactNode;
  className?: string;
};

export function DataTable<T>({
  columns,
  items,
  rowKey,
  empty,
}: {
  columns: Column<T>[];
  items: T[];
  rowKey: (item: T) => string;
  empty?: ReactNode;
}) {
  if (items.length === 0) {
    return <>{empty ?? null}</>;
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className={column.className}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={rowKey(item)} className="data-table-row">
              {columns.map((column) => (
                <td key={column.key} className={column.className}>
                  {column.render(item)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
