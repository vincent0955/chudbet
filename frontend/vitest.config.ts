import { mergeConfig, defineConfig } from 'vitest/config'
import viteConfig from './vite.config'

// Keep unit tests (Vitest) scoped to src/ so Playwright e2e specs under e2e/
// are not collected by the unit runner.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      include: ['src/**/*.test.{ts,tsx}'],
      exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
    },
  }),
)
