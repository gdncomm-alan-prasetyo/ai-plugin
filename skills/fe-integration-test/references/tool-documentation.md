# @blibli/integration-test-tools — Documentation

> **This is the canonical, human-readable reference for the tool**, exported from the GDN Confluence page so it lives with the plugin and stays readable offline. **The Confluence link is deprecated as the primary reference — use this file.** Workflow guidance lives in the sibling references; this file is the "what does each thing do" lookup.
>
> **Source:** [@blibli/integration-test-tools Documentation](https://gdncomm.atlassian.net/wiki/spaces/GDNIT/pages/515475132/blibli+integration-test-tools+Documentation) — GDN Confluence (GDNIT), owned by R&D Frontend Team (Resly Suniar).
> **Exported from:** page version 20, last updated 2025-09-11.

> **Versions move.** This export is current as of tool **2.12.0**, which still pins **Playwright `1.58.0`** as the *client* but runs the patched **runner image `bliblidotcom/playwright-runner:1.58.1`** (`arm64-`-prefixed on Apple Silicon; the tool maps client → image since 2.10.0, so the image tag ≠ the client version). The historical changelog entries below quote the Playwright version that shipped with each release. The project under test may pin a different version — always confirm the installed version and the project's own script names via the [Version Gate](../SKILL.md#version-gate) rather than trusting the numbers here.

## Table of Contents

1. [Tech stack](#tech-stack)
2. [Installation & init](#installation--init)
3. [Configuration](#configuration)
4. [Generate test suites (test-scenarios.js)](#generate-test-suites-test-scenariosjs)
5. [Mocking API data](#mocking-api-data)
6. [Taking snapshots](#taking-snapshots)
7. [Utils API reference](#utils-api-reference)
8. [Recommended workflow: start broad, then deep](#recommended-workflow-start-broad-then-deep)
9. [Changelog](#changelog)
10. [Contributing](#contributing)

---

## Tech stack

| Concern | Tooling |
|---|---|
| Framework | `jest` (jest-circus runner) |
| Browser Runner | `playwright@1.58.0` (pinned at tool 2.8.5) |
| Machine Runner | `docker` or native macOS `container` CLI (auto-detected, tool >= 2.9.0) |
| Coverage | **V8** (default since 2.9.1) or Istanbul format, `nyc` for report merge |
| Snapshot diff | `jest-image-snapshot` |
| Docker image | `docker pull bliblidotcom/playwright-runner:1.58.0` (AMD + ARM) |

---

## Installation & init

```bash
npm install --save-dev @blibli/integration-test-tools@latest
npx blibli-integration init
```

`init` scaffolds the project. Files it generates or appends to:

| File | Action |
|---|---|
| `blibli-integration-test.config.js` | Create |
| `.gitignore` | Append |
| `.gitattributes` | Append |
| `package.json` | Append (scripts) |
| `/integrations/specs/test-feature/` | Create |
| `desktop-test.spec.js` & `mobile-test.spec.js` | Create |
| `sonar-project.properties.default` | Append |
| `.babelrc` | Append |
| `Jenkinsfile` | Append |

> Since **2.1.0** the project is ESM (`"type": "module"`) and the config must be renamed `blibli-integration-test.config.cjs`.

---

## Configuration

A single config file centralizes all settings. Define your app, the Playwright options, coverage exclusions, and mocking.

### Standalone project

```js
module.exports = {
  // define your collab or standalone app here
  app: {
    // script to run collab or standalone app in no mock mode
    script: 'dev-nomock',
    // url to main.js/app.js for collab, and localhost+port for standalone app
    waitUrls: ['http-get://localhost:10027/product-detail/static/js/app.js'],
    // api mock path
    mockPaths: ['/src/api-mock/index']
  },
  playwright: {
    headless: true,        // default true (deprecated — inspector mode supersedes)
    devtools: false,
    debug: false,
    bail: false,           // stop after first failure
    inspector: false,
    setRetry: false,
    retryTimes: 3,
    rerunOnlyFailures: false
  },
  // remove if you don't want to exclude file coverage
  nyc: { exclude: [/* 'src/main.js' */] },
  // remove if you don't use unit testing
  unitTest: { coverageFinalJsonPaths: ['test/unit/coverage/coverage-final.json'] },
  jestCli: [/* https://jestjs.io/docs/cli */],
  // remove if you don't need to mock
  mock: { /* ... */ }
}
```

### Micro-frontend / collab project

Adds a `mainUi` block (the host shell) alongside `app`:

```js
module.exports = {
  mainUi: {
    repository: 'ssh://git@stash.gdn-app.com:7999/trfeae/pyeongyang-ui-main.git',
    branch: 'feature/integration-test-jest',
    targetDir: 'ui-main',
    waitUrls: ['https-get://localhost:10001'],   // http-get if no TLS
    mockPath: 'integrations/_blibli/ui-main/src/api-mock/index',
    script: 'dev-nomock-desktop'
  },
  app: {
    script: 'dev-nomock',
    waitUrls: ['http-get://localhost:10027/product-detail/static/js/app.js'],
    mockPaths: ['/src/api-mock/index']
  },
  playwright: { /* same as standalone */ }
}
```

### `playwright` options

| Option | Type | Default | Notes |
|---|---|---|---|
| `headless` | Boolean | `true` | Deprecated — inspector mode replaces it. |
| `devtools` | Boolean | `false` | Show Chromium DevTools in inspector mode. |
| `debug` | Boolean | `false` | Show Playwright log in terminal. |
| `bail` | Boolean | `false` | Stop after the first failure. |
| `inspector` | Boolean | `false` | **1.9.0+** — visual inspector window (start/pause/step/record). |
| `setRetry` | Boolean | `false` | **1.9.7+** — retry failed tests until pass or max retries. |
| `retryTimes` | Integer | `3` | Max retries. |
| `rerunOnlyFailures` | Boolean | `false` | **1.9.13+** — rerun only previously-failed tests; uses `runInBand` (1 worker), slower. |

### `host` helper (for `page.goto` URLs)

| API | Returns |
|---|---|
| `host.isDocker` | Boolean. |
| `host.name` | `'localhost'` or `'host.docker.internal'` based on `isDocker`. **Use this instead of hardcoding `'localhost'`.** |
| `host.targetHost` | `host.name` + `:port` (needs the `port` key in config). Falls back to `host.name` if no port. |

```js
const host = require('@blibli/integration-test-tools/lib/utils/host')
if (host.isDocker) await page.waitForTimeout(1_000)
await page.goto(`https://${host.name}:10001/member/order/digital/completed`)
await page.goto(`https://${host.targetHost}/member/order/digital/completed`)
```

To use `host.targetHost`, add `port` to the config:

```js
// Collab
mainUi: { ..., port: '10001' },
// Standalone
app: { ..., port: '10001' },
```

---

## Generate test suites (test-scenarios.js)

Available on **1.9.14+**. Declare scenarios as data; the generator transpiles them into specs.

```bash
npx blibli-integration generate
```

Provide `./integrations/test-scenarios.js` (an array of test objects):

| Key | Type | Description |
|---|---|---|
| `testName` | String | Spec file name to create. |
| `testDescription` | String | `describe` block description. |
| `url` | String | URL for `page.goto`. |
| `viewportSize` | String | `DESKTOP` → `setDesktop`; `MOBILE` → `setMobile`. |
| `mockUpdates` | Array<Object> | API mocks; each becomes a `$blibli.mock.update({})`. |
| `cases` | Array<Object> | Test cases. |
| `cases.caseName` | String | Test case description. |
| `cases.interactions` | Array<Object> | Ordered interactions. Supported: `scrollToSelector`, `click`. (More to come.) |

```jsonc
[
  {
    "testName": "ExampleFeatureNameToTest",
    "testDescription": "Homepage should load well",
    "url": "https://blibli.com",
    "viewportSize": "DESKTOP",
    "mockUpdates": [
      {
        "method": "GET",
        "url": "/backend/content-api/promotions/components/parameters/product-tab-1/products?item_per_page=15&brsSource=INFINITE&page=2",
        "status": 200,
        "response": { "data": [] }
      }
    ],
    "cases": [
      {
        "caseName": "See all button clicked and show all products",
        "interactions": [
          { "interaction": "scrollToSelector", "selector": ".promo-section" },
          { "interaction": "click", "selector": ".button-see-all" }
        ]
      }
    ]
  }
]
```

Generated spec (`integrations/specs/.temp/ExampleFeatureNameToTest.spec.js`):

```js
const networkUtil = require('@blibli/integration-test-tools/lib/utils/network')
const responsiveUtil = require('@blibli/integration-test-tools/lib/utils/responsive')
const interactionUtil = require('@blibli/integration-test-tools/lib/utils/interaction')
const snapshotUtil = require('@blibli/integration-test-tools/lib/utils/snapshot')

describe('Homepage should load well', () => {
  beforeAll(async () => {
    await responsiveUtil.setDesktop(page)
    $blibli.mock.update({
      method: 'GET',
      url: '/backend/content-api/.../products?item_per_page=15&brsSource=INFINITE&page=2',
      status: 200,
      response: { "data": [] }
    })
    await page.goto('https://blibli.com')
    await networkUtil.waitForNetworkIdle(page, 1000, 1)
  })

  test('See all button clicked and show all products', async () => {
    await interactionUtil.scrollToSelector(page, '.promo-section')
    await page.click('.button-see-all')
    await snapshotUtil.assertComponentSnapshot(expect, page)
  })
})
```

`integration:base` auto-generates from `test-scenarios.js` when present, so you can just run the suite.

---

## Mocking API data

### Update / add a mock

In-page global `$blibli.mock.update(routeObject)`:

```js
$blibli.mock.update(routeObject)

routeObject = {
  status,          // [int] HTTP response code
  contentType,     // default 'application/json'
  url,             // [string] url
  method,          // 'GET' | 'POST' | 'PUT' | 'DELETE'
  param_values,    // values of params as key-value pair
  response,        // Object response from mock
  delay,           // delay of response in ms
  response_header  // Object of response headers, if any
}
```

### Reset

```js
$blibli.mock.reset()
```

Deeper matching rules and where to persist mocks: [auto-mocks.md](./auto-mocks.md).

---

## Taking snapshots

```js
const { assertComponentSnapshot } = require('@blibli/integration-test-tools/lib/utils/snapshot')
```

Signature:

```
assertComponentSnapshot({ expect, page, selector, options: { screenshot, assertConfig, network } })
```

- **`expect`** — Playwright's `expect` currently used in the test.
- **`page`** — Playwright page instance to capture.
- **`selector`** — CSS selector or xpath. Empty → full-page screenshot.
- **`options.screenshot`** — passed to Playwright's [`page.screenshot`](https://playwright.dev/docs/screenshots).
- **`options.assertConfig`** — passed to [`jest-image-snapshot`'s `toMatchImageSnapshot`](https://github.com/americanexpress/jest-image-snapshot#%EF%B8%8F-api).
- **`options.network`** — network wait before snapshot. Default `{ timeout: 100, maxInflightRequest: 1 }`. Raise `maxInflightRequest` to 2+ for preloaded screens.

```js
// Viewport-size snapshot
await assertComponentSnapshot({ expect, page })

// Full-page snapshot
await assertComponentSnapshot({ expect, page, options: { screenshot: { fullPage: true } } })

// Specific component
await assertComponentSnapshot({ expect, page, selector: '.css-selector' })
```

> **Deprecated:** `assertSnapshot(expect, page, parameters)` was replaced by `assertComponentSnapshot` in **1.8.0+**.

---

## Utils API reference

Each util is a separate import under `@blibli/integration-test-tools/lib/utils/`.

### `stopAnimations(page)` — `utils/animation.js`

Disables animations/transitions so elements stay static for stable screenshots. Put it after `page.goto`.

```js
const { stopAnimations } = require('@blibli/integration-test-tools/lib/utils/animation.js')
// in beforeAll, after page.goto:
await stopAnimations(page)
```

### `clickElement(page, selector)` — `utils/click.js`

Click a specific element by CSS selector.

```js
const { clickElement } = require('@blibli/integration-test-tools/lib/utils/click.js')
await clickElement(page, SELECTOR)
```

### `assertDataLayerEvent(expect, page, { event })` — `utils/datalayer.js`

Assert a `dataLayer` analytics event fired. `event`: `id` (String), `index` (Number, optional default 0), `key` (String dot-notation filter, optional), `partialObj` (Object to match — `pageType`, `eventDetails`, `ecommerce`, …).

```js
const { assertDataLayerEvent } = require('@blibli/integration-test-tools/lib/utils/datalayer.js')
await dataLayerUtil.assertDataLayerEvent(expect, page, {
  event: {
    id: 'productImpressionRetail',
    index: 1,
    partialObj: {
      pageType: 'retail-promotion',
      eventDetails: { category: 'retail-promotion' },
      ecommerce: { impressions: [{ list: 'Promotion FLASH_SALE/FS NOT Lazy Load UPCOMING' }] }
    }
  }
})
```

### `scrollToSelector(page, selector)` — `utils/interaction`

Scroll to where a component is defined.

```js
const { scrollToSelector } = require('@blibli/integration-test-tools/lib/utils/interaction')
await scrollToSelector(page, SELECTOR)
```

### `scrollTo(page, { x, y })` — `utils/interaction`

Scroll to a pixel position.

```js
const { scrollTo } = require('@blibli/integration-test-tools/lib/utils/interaction')
await scrollTo(page, { x: 0, y: 1000 })
```

### `handleClickOpenNewTab(page, selector)` — `utils/navigation.js`

**1.9.13+.** Handle a click that opens a new browser tab.

```js
const { handleClickOpenNewTab } = require('@blibli/integration-test-tools/lib/utils/navigation.js')
await page.click('button:has-text("Ajukan Kendala")')
await handleClickOpenNewTab(page, '.blu-modal__container .blu-list > ul > li:nth-child(1) > button')
await snapshotUtil.assertComponentSnapshot({ expect, page, options })
```

### `disableNavigation(page)` — `utils/navigation`

**1.9.13+.** Required when a test interaction causes a same-page redirect (`window.location.href` or an anchor). Put it **after** `page.goto`.

```js
const { disableNavigation } = require('@blibli/integration-test-tools/lib/utils/navigation')
// in beforeAll, after page.goto:
await disableNavigation(page)
```

### `waitForNetworkIdle(page, timeout, maxInflightRequests)` — `utils/network.js`

Wait for network requests to finish. If a request exceeds **30s**, the test terminates and prints a request-status table — mock each listed request. Put it after `page.goto`.

```js
const { waitForNetworkIdle } = require('@blibli/integration-test-tools/lib/utils/network.js')
await waitForNetworkIdle(page, 1000, 1)
```

### `setMobile(page, { width, height })` — `utils/responsive`

Set the viewport to mobile (default `360×640`). Put it in the first line of `beforeAll`.

**Since 2.9.2:** also sets a mobile `User-Agent` at both layers — the outgoing request header (for SSR device detection) **and** `navigator.userAgent` via an init script (for client-side detection). Call **before** `page.goto` so the init script takes effect on the first navigation.

```js
const { setMobile } = require('@blibli/integration-test-tools/lib/utils/responsive')
await setMobile(page)                              // defaults
await setMobile(page, { width: 480, height: 2000 }) // custom
```

### `setDesktop(page, { width, height })` — `utils/responsive`

Set the viewport to desktop (default `1280×720`).

**Since 2.9.2:** also sets a desktop `User-Agent` at both layers (same as `setMobile`). Call before `page.goto`.

```js
const { setDesktop } = require('@blibli/integration-test-tools/lib/utils/responsive')
await setDesktop(page)
await setDesktop(page, { width: 1280, height: 4000 })
```

### `sizes`

Default viewport config:

```js
const sizes = {
  mobile:  { width: 360,  height: 640 },
  desktop: { width: 1280, height: 720 }
}
```

---

## Recommended workflow: start broad, then deep

The tool's intended authoring flow (matches this skill's coverage-driven approach):

1. **Start wide** — test every route by loading each full page. The test generator (**1.9.14+**) does this.
2. **Check coverage** — read the coverage report to see what's tested and what isn't.
3. **Dive deeper** — write detailed tests for the uncovered lines/functions found in step 2.

Operationalized in [coverage-driven-flows.md](./coverage-driven-flows.md).

---

## Changelog

> **Current** — at tool **2.12.0** the pinned Playwright **client** is still **`1.58.0`** but the **runner image** is **`bliblidotcom/playwright-runner:1.58.1`** (`arm64-`-prefixed on Apple Silicon; client→image map added in 2.10.0). The historical entries below quote the Playwright version that shipped with each release.

### 2.12.0 (2026-07-10)
- **Feature:** Opt-in **CSS coverage ("junk" detection)** (GOTH-4565). Collects which CSS byte ranges each spec actually used during the Playwright run, then reports shipped-but-unused CSS ("junk") — especially useful for DLS component libraries where a page loads far more CSS than any one component renders. Runs **independently of the JS coverage `provider`** (`v8`/`istanbul`). Enable via a `coverage.css` block: `{ enabled, include, exclude, threshold, failOnThreshold, openReport }` (all default off/empty; `threshold: null` disables the gate). Per-spec used ranges are written to `integrations/.css_coverage/`; at report time they're merged (a rule used by *any* spec counts as used) via `monocart-coverage-reports` into `integrations/coverage-css/index.html`, `integrations/coverage-css/css-coverage-summary.json` (`{ generatedAt, totalBytes, usedBytes, unusedBytes, usedPct, junkPct, threshold, files }`), plus a console summary of the worst stylesheets. Both new dirs are added to the `.gitignore` template. Full config surface + option table: [coverage-optional-extras.md](./coverage-optional-extras.md#css-coverage-junk--unused-css-detection--2120).

### 2.11.0 (2026-06-29)
- **Enhancement:** Scroll behavior is reset to `auto` on the initial load of every page. A context-level init script sets `document.documentElement.style.scrollBehavior = 'auto'` (at document start and again on `DOMContentLoaded` for every navigation) so pages declaring `scroll-behavior: smooth` no longer animate scrolling during tests — making scroll-based interactions and screenshots deterministic. No per-spec change required. (GOTH-4449)

### 2.10.1 (2026-06-26)
- **Change:** The local runner-version check now validates the Jenkinsfile against the runner **image** version, not the bundled Playwright version. Because Playwright `1.58.0` runs on the patched Ubuntu Noble image `1.58.1`, `checkVersionCompatibility()` confirms the Jenkinsfile matches the resolved runner image version (e.g. `1.58.1`). The check is **local-only** (skipped in CI via `is-ci`).
- **Added:** `RUNNER_IMAGE_VERSION` is exported from `src/helpers/docker/playwright.js` — the resolved runner image tag the tool pulls.
- **Action required:** Projects on Playwright `1.58.0` should set the runner **image** version in their Jenkinsfile: `playwright: [ enabled: true, version: '1.58.1' ]`.

### 2.10.0 (2026-06-26)
- **Change:** Pull the patched Ubuntu Noble runner image `1.58.1` for the Playwright `1.58.0` client. Adds `RUNNER_IMAGE_TAG_BY_PLAYWRIGHT_VERSION` in `src/helpers/docker/playwright.js`, mapping the Playwright client version → the runner image tag. This **decouples the runner image tag from the bundled Playwright version**, so the image can be security-patched/rebuilt (Jammy → Noble) independently. The `1.58.1` image still ships Playwright `1.58.0` internally, so client and in-image server stay compatible. Resolved image: `bliblidotcom/playwright-runner:1.58.1` (`arm64-1.58.1` on Apple Silicon). **Impact for this skill:** the runner image tag no longer equals the Playwright client version — resolve the image from the tool, don't derive it from the Playwright dep (see [run-modes.md](./run-modes.md#reuse-detection-run-before-starting-anything)).

### 2.9.2 (2026-06-23)
- **Feature:** `setMobile` / `setDesktop` now set a device-appropriate user agent at **both layers**: the outgoing `User-Agent` request header (read by the SSR layer) and `navigator.userAgent` (overridden via an init script for client-side detection). Must be called before `page.goto`.
- **Feature:** Isolated coverage gathering for parallel test runs via `BLIBLI_COVERAGE_NAMESPACE` — coverage temp/merge/report directories are namespaced per run so concurrent suites don't clobber each other's data. See [coverage-driven-flows.md](./coverage-driven-flows.md#parallel-coverage-isolation-blibli_coverage_namespace).
- **Enhancement:** Capture a failure screenshot on assertion failures (not just timeout / element-not-found), labelled `assertion` in the test report.
- **Fix:** Skip subdirectories (e.g. namespaced coverage dirs) when scanning `.nyc_output` for the V8 monocart report.

### 2.9.1 (2026-06-18)
- **Enhancement:** Default coverage provider changed from `istanbul` to **`v8`** in the default config (`blibli-integration-test.config.js`). Projects without an explicit `coverage.provider` now use V8.
- **Enhancement:** Warn (instead of silently ignoring) when `INTEGRATION_CONTAINER_RUNTIME` is set to an unrecognized value, then auto-detect.
- **Enhancement:** Clamp the mac runner's default memory to the host RAM minus headroom so `container run -m` can't request more RAM than exists.
- **Enhancement:** Only fall back to docker on a mac-container daemon-start failure when docker is actually installed; otherwise surface a clear error and abort early.
- **Enhancement:** Honor a user-provided `playwright.image` (e.g. a mirrored registry) instead of always forcing the default runner image.
- **Refactor:** Single source of truth for the runner image string, shared by `docker:run` and `docker:stop`.

### 2.9.0 (2026-06-12)
- **Feature:** Native macOS container support. On macOS, `docker:run` / `docker:stop` auto-detect and use the native Apple `container` CLI when available (faster local runs, no Docker Desktop), falling back to Docker when unavailable. Override with `INTEGRATION_CONTAINER_RUNTIME=docker|container`.
- **Feature:** Auto-start the mac container daemon (`container system start`) when needed.
- **Feature:** Host networking via `host.container.internal` — resolves to the host loopback through the runtime's `--localhost` DNS redirect (firewall-friendly). `docker:run` prints the one-time `sudo container system dns create … --localhost …` setup command when the domain isn't registered.
- **Feature:** Size the mac runner with a conservative default of **6 CPUs** (capped to host count) and **6 GiB** to prevent OOM across jest workers. Override with `APPLE_CONTAINER_CPUS` / `APPLE_CONTAINER_MEMORY`.

### 2.2.0 (2025-08-27)
**Feature**: Add V8 coverage provider support
- Feature: Add config for `debugMock` to avoid too much info flow
- Enhancement: Implement V8 to Istanbul coverage format conversion
- Performance: Improve coverage processing with better error handling

### 2.1.5 (2025-08-22)
**Bug fix** — Fix use jest `testMatch` from ssr config.

### 2.1.4 (2025-08-18)
**Feature** — Add config `ssr` attribute for SSR integration test.

### 2.1.3 (2025-07-03)
**Bug fix** — Handle api mock for POST method with file upload.

### 2.1.2 (2025-06-05)
**Bug fix** — Converts any OS-specific path into a valid `file://` URL to support all OS.

### 2.1.1 (2025-05-28)
**Bug fix** — Load API mock files from ESM project.

### 2.1.0 (2025-05-21)
**Breaking change**
- Project now supports ESM (`"type": "module"`).
- Users must rename their `blibli-integration-test.config.js` to `blibli-integration-test.config.cjs`.

### 2.0.1 (2025-05-07)
**Bug Fixes**
- Lock playwright version at `1.51.0` to prevent client and server version mismatch
- Update docker version matcher to support tools version >= 2

### 2.0.0 (2025-05-07)
**Features**
- GOTH-4301 validate `maxWorker` number used on Jenkins CI
- GOTH-4207 Prevent `page.reload()` usage in integration test spec.js
- Add version notifier post-install to notify user if a newer version is available

**Bug Fixes**
- GOTH-4185 Refine the error message to make it more descriptive

**Dependencies** — `playwright@1.51.0`

**Breaking Changes ⚠️** — Due to the upgrade of Playwright from `1.38.1` to `1.51.0`, baseline image differences are expected as a result of the Chromium version update.

### 1.10.1 (2025-01-16)
**Dependencies** — `wait-on@8.0.2`
**Chores** — GOTH-3127 Fix 6 vulnerabilities (4 moderate, 2 high)

### 1.10.0 (2024-10-25)
**Features** — Performance improvement: update save coverage method in jest environment
**Bug Fixes** — GOTH-4177 fix `isDocker` to support GKS environment
**Dependencies** — `is-ci@3.0.1`

---

## Contributing

Inspired to help? Your contributions can drive this module forward — feel free to contact the **R&D Frontend Team** through Microsoft Teams or Email.

**Great heads up and thanks to:** Deviani, Adhika Setya Pramudika.

**Contributors:** Juan Tjandra, Karnando Sepryan, Muhammad Pazrin Andreanor, Vito Rizki Imanda, Herman.

Feel free to reach out to the module's maintainers for any questions or issues.
