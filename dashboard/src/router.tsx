import {
  createRootRoute,
  createRoute,
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";
import { App } from "./app";
import { OverviewPage } from "./pages/overview-page";
import { ProvenancePage } from "./pages/provenance-page";
import { ResultsPage } from "./pages/results-page";
import { parseSearch, stringifySearch, type DashboardSearch } from "./navigation";

const rootRoute = createRootRoute({
  component: App,
  validateSearch: (search: Record<string, unknown>): DashboardSearch =>
    Object.fromEntries(
      Object.entries(search).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    ),
  notFoundComponent: OverviewPage,
});
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: OverviewPage,
});
const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/overview",
  component: OverviewPage,
});
const fittingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/fitting",
  component: () => <ResultsPage kind="fitting" />,
});
const refinementsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/refinements",
  component: () => <ResultsPage kind="refinements" />,
});
const provenanceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/provenance",
  component: ProvenancePage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  overviewRoute,
  fittingRoute,
  refinementsRoute,
  provenanceRoute,
]);

export function createDashboardRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    parseSearch,
    stringifySearch,
    history,
  });
}
export const router = createDashboardRouter();
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
