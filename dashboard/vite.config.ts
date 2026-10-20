import { defineConfig } from "vite-plus";

export default defineConfig({
  fmt: { printWidth: 100, ignorePatterns: ["dist/**"] },
  lint: { options: { typeAware: true, typeCheck: true } },
  test: { include: ["src/**/*.test.ts"] },
});
