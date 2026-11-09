import { useId, type ReactNode } from "react";

export function PanelHelp({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();

  return (
    <div className="panel-help">
      <button type="button" popoverTarget={id} aria-label={label} title={label}>
        <span aria-hidden="true">?</span>
      </button>
      <div
        id={id}
        className="panel-help-content"
        popover="auto"
        role="note"
        aria-label={label}
        onBeforeToggle={(event) => {
          if (event.newState !== "open") return;
          const popover = event.currentTarget;
          const button = popover.previousElementSibling!.getBoundingClientRect();
          popover.style.top = `${button.bottom + 8}px`;
          popover.style.right = `${Math.max(12, window.innerWidth - button.right)}px`;
        }}
      >
        {children}
      </div>
    </div>
  );
}
