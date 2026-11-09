import { useEffect, useState } from "react";

export function CopyPathButton({ path, label }: { path: string; label: string }) {
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (!status) return;

    const timer = setTimeout(() => setStatus(""), 2000);

    return () => clearTimeout(timer);
  }, [status]);

  return (
    <button
      type="button"
      title={path}
      aria-label={`Copy ${label.toLowerCase()} path`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(path);
          setStatus("Copied");
        } catch {
          setStatus("Copy failed");
        }
      }}
    >
      <svg
        aria-hidden="true"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <rect x="8" y="8" width="12" height="14" rx="2" />
        <path d="M16 8V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" />
      </svg>
      {label}
      <span role="status">{status}</span>
    </button>
  );
}
