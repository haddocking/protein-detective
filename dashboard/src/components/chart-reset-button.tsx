import type { ReactNode } from "react";

export function ChartResetButton({
  onReset,
  disabled,
  label,
  children,
}: {
  onReset: () => void;
  disabled: boolean;
  label: string;
  children: ReactNode;
}) {
  return (
    <button
      className="chart-reset"
      onClick={onReset}
      disabled={disabled}
      aria-label={label}
      title="Reset view"
    >
      {children}
    </button>
  );
}
