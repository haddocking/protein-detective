// Started by `protein-detective dashboard --dev`; keep API cookies on the Vite origin.
import { createServer } from "vite-plus";

const [host, port, target] = process.argv.slice(2);
const server = await createServer({
  server: {
    host,
    port: Number(port),
    strictPort: true,
    open: false,
    proxy: {
      "^/(api|files)(/|$)": { target, changeOrigin: false },
    },
  },
});
// EOF also handles Node version-manager shims that launch Node as a child process.
process.stdin.resume();
process.stdin.on("end", async () => {
  await server.close();
  process.exit(0);
});
await server.listen();
const address = server.httpServer.address();
console.log(`PROTEIN_DETECTIVE_DEV_PORT=${address.port}`);
