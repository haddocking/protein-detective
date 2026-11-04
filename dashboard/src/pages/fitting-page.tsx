import { FittingChartPanel } from "../components/fitting-chart-panel";
import { ResultsLayout } from "../components/results-layout";
import { useResults } from "../hooks/use-results";
import { useSession } from "../hooks/use-session-data";

export function FittingPage() {
  const results = useResults("fitting");
  const { summary } = useSession();
  return (
    <ResultsLayout
      kind="fitting"
      results={results}
      noun="solutions"
      scoreHint="Higher PowerFit CC is better"
      beforeTable={
        !Number(summary.fitted_structures) && (
          <p className="notice">
            Solutions exist but fitted structures have not been saved. Run{" "}
            <code>protein-detective powerfit fit-models</code> to enable 3D viewing.
          </p>
        )
      }
    >
      <FittingChartPanel rows={results.filtered} />
    </ResultsLayout>
  );
}
