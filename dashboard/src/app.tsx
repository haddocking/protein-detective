import { SessionProvider } from "./components/session-provider";
import { SessionLayout } from "./components/session-layout";

export function App() {
  return (
    <SessionProvider>
      <SessionLayout />
    </SessionProvider>
  );
}
