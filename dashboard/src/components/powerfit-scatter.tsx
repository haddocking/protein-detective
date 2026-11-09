import { Scatter, type ScatterProps } from "./scatter";
import { useRefinementsNavigation } from "../hooks/use-result-navigation";

export function PowerfitScatter(props: ScatterProps) {
  const { selectedId } = useRefinementsNavigation();

  return (
    <Scatter
      {...props}
      before="before_cc"
      after="after_cc"
      title="PowerFit CC"
      selectedId={selectedId}
    />
  );
}
