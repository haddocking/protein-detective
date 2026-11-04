import { PageTitle } from "../components/page-title";
import React, { useState, type ReactNode } from "react";
import { display, sorted } from "../data";
import { useSession } from "../hooks/use-session-data";
export function ProvenancePage() {
  const { data } = useSession();
  const [copied, setCopied] = useState("");
  let content: ReactNode;
  if (!data.provenance) {
    content = <p>Loading provenance…</p>;
  } else if (!data.provenance.length) {
    content = <p className="empty">No recorded workflow commands.</p>;
  } else {
    content = sorted(data.provenance, "start_time", false).map((r, i) => (
      <section className="provenance" key={i}>
        <div className="section-heading">
          <span className="step">{i + 1}</span>
          <code>{display(r.command)}</code>
          <button
            onClick={() =>
              navigator.clipboard.writeText(display(r.command)).then(() => setCopied(String(i)))
            }
          >
            {copied === String(i) ? "Copied" : "Copy command"}
          </button>
        </div>
        <details>
          <summary>{display(r.start_time)} · Inspect timestamps and recorded paths</summary>
          <dl>
            {Object.entries(r)
              .filter(([k]) => k !== "command")
              .map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt>{k.replaceAll("_", " ")}</dt>
                  <dd>
                    <pre>{typeof v === "object" ? JSON.stringify(v, null, 2) : display(v)}</pre>
                  </dd>
                </React.Fragment>
              ))}
          </dl>
        </details>
      </section>
    ));
  }
  return (
    <>
      <PageTitle />
      <p className="muted">Recorded workflow commands and their inputs and outputs.</p>
      {content}
    </>
  );
}
