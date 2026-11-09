import { lazy, Suspense } from "react";
import { display, fileUrl, sorted, type Row } from "../data";
import { useRefinementsNavigation } from "../hooks/use-result-navigation";

const StructureViewer = lazy(() =>
  import("../viewer").then((m) => ({ default: m.StructureViewer })),
);

export function BestStructure({ refinements }: { refinements: Row[] }) {
  const { select } = useRefinementsNavigation();
  const best = sorted(
    refinements.filter((r) => r.viewer_available),
    "after_cc",
    true,
  )[0];

  if (!best) return null;

  return (
    <section className="best-structure">
      <div className="section-heading">
        <h2>Best refined structure by PowerFit CC score</h2>
        <button className="text-link" onClick={() => select(best)}>
          {display(best.structure)} · {display(best.refine_run_id)} · PowerFit CC{" "}
          {display(best.after_cc)} →
        </button>
      </div>
      <Suspense fallback={<p>Loading 3D viewer…</p>}>
        <StructureViewer
          structureUrl={fileUrl(best.model_path)}
          densityUrl={fileUrl(best.density_path)}
          refinedKnownStructureUrl={fileUrl(best.refined_known_structure)}
          refined
          label={display(best.structure)}
        />
      </Suspense>
    </section>
  );
}
