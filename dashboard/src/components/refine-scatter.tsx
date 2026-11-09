import { Scatter, type ScatterProps } from "./scatter";
import { useRefinementsNavigation } from "../hooks/use-result-navigation";

export function RefineScatter(props: ScatterProps) {
  const { selectedId } = useRefinementsNavigation();

  return (
    <Scatter
      {...props}
      before="baseline_score"
      after="refined_score"
      title="HADDOCK score"
      selectedId={selectedId}
    />
  );
}
