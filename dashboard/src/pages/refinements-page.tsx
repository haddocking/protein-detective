import { HaddockChartPanel } from "../components/haddock-chart-panel";
import { PowerfitCcChartPanel } from "../components/powerfit-cc-chart-panel";
import { ResultsLayout } from "../components/results-layout";
import { useResults } from "../hooks/use-results";

export function RefinementsPage() {
  const results = useResults("refinements");
  return (
    <ResultsLayout
      kind="refinements"
      results={results}
      noun="members"
      scoreHint="PowerFit CC: positive is better. HADDOCK score: negative is better."
    >
      <div className="comparison-charts">
        <HaddockChartPanel rows={results.selectedRows} onSelect={results.chartSelect} />
        <PowerfitCcChartPanel rows={results.selectedRows} onSelect={results.chartSelect} />
      </div>
    </ResultsLayout>
  );
}
