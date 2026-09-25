---
name: fe-integration-test
description: "Write UI integration tests for any Blibli frontend repo using @blibli/integration-test-tools v2 (Jest globals + Playwright page). Self-contained: discovers and reuses this repo's own helpers (toast/verifyToast, setup helpers, locators, mock-generators, snapshot) instead of hardcoding one project's layout, and covers the full v2 API (navigation, snapshots, mocks/failure states, scroll/delay, viewports). Use when adding or extending a .spec.js file under an integrations/specs/ (or equivalent) tree, or when asked to run the existing integration test suite."
allowed-tools: Read Write Edit Glob Grep Bash
user-invocable: true
metadata:
  color: "green"
  aliases: "write ui integration test, new integration spec, run integration test, run ui integration test, run integration tests"
compatibility: "Any Blibli UI repo using @blibli/integration-test-tools v2.x with Jest-style globals (describe/test/beforeAll, global page/$blibli.mock) and specs under an integrations/specs/<feature>/<desktop|mobile>/ tree. Helper file names/paths vary per repo — see Discovery below."
---

# Write Integration Test — Blibli UI repos (v2)

Write **UI integration test specs** using `@blibli/integration-test-tools` **v2** and Playwright,
for any repo that follows this convention — not just one project. Two things make this different
from writing a spec from scratch:

1. **Discover, don't assume.** Helper paths and function names (toast, snapshot, locators, setup,
   mock-generators) vary between repos. Always run [Step 0](#step-0--discover-this-repos-helpers-before-writing-anything)
   first and use whatever this repo actually exports.
2. **Reuse project helpers over ad-hoc code.** Once discovered, prefer this repo's own toast /
   snapshot / setup / mock-generator helpers over hand-rolled timers, raw `$blibli.mock.update`
   calls, or inline CSS selectors.

---

## Table of Contents

1. [Version Gate](#version-gate)
2. [Step 0 — Discover this repo's helpers](#step-0--discover-this-repos-helpers-before-writing-anything)
3. [When to Use This Skill](#when-to-use-this-skill)
4. [Step 0b — Check for UI documentation](#step-0b--check-for-ui-documentation)
5. [Quick Start](#quick-start)
6. [Running the tests](#running-the-tests)
7. [Spec skeleton](#spec-skeleton)
8. [Toast checklist](#toast-checklist--use-whenever-an-action-can-trigger-a-toast)
9. [Redirection checklist](#redirection-checklist--use-whenever-an-action-navigatesredirects-the-page)
10. [Other kinds of helpers to look for and reuse](#other-kinds-of-helpers-to-look-for-and-reuse)
11. [Writing new helper functions](#writing-new-helper-functions)
12. [Pattern Files](#pattern-files)
13. [References](#references)
14. [Decision Guide](#decision-guide)
15. [Implementation Checklist](#implementation-checklist)
16. [Troubleshooting](#troubleshooting)

---

## Version Gate

**Run this check before doing anything else.**

```bash
node -e "const p = require('./node_modules/@blibli/integration-test-tools/package.json'); console.log(p.version)"
```

- If the command fails (module not found): tell the user `@blibli/integration-test-tools` is not
  installed and stop.
- If the version starts with **`2.`** → proceed normally, this skill applies.
- If the version starts with **`3.`** or higher → **stop** and tell the user:

  > This skill is for `@blibli/integration-test-tools` **v2** only. This repo has **vX.Y.Z**
  > installed, which is v3 or newer. Use a v2→v3 migration skill, or a v3-specific test-writing
  > skill, instead.

Do not write any test code until the version gate passes.

---

## Step 0 — Discover this repo's helpers before writing anything

```bash
# find the helpers/utils directory for integration tests
find . -path '*/node_modules' -prune -o -type d \( -iname helpers -o -iname utils \) -path '*integrations*' -print
# find the toast helper specifically
find . -path '*/node_modules' -prune -o -type f -iname 'toast.js' -path '*integrations*' -print
```

Then `Read` that toast helper and note its **actual** exported names — repos have been seen with
all of these variants:

| Function | Seen as |
|---|---|
| verify a toast appeared | `verifyToast` (consistent across repos so far) |
| verify N toasts stacked | `verifyMultipleToast` (not present in every repo) |
| stub the timer | `mockSetTimeout` (consistent) |
| restore timer + clear toast DOM | `resetTimeoutAndRemoveToast` **or** `resetTimeoutAndHideToast` **or** `resetTimeoutAndHideToastOld` — pick whichever this repo exports, don't assume the name |

Also locate, the same way (`find`/`grep` under this repo's `integrations/` tree), before writing
a spec:
- the **locator** file (selectors/`data-testid` map)
- **setup helpers** for mocking common API responses (member config, address list, current user, etc.) or bundling viewport+goto+wait
- **mock-generators** / fixture builders for response bodies
- the **snapshot** helper (`assertContentSnapshot` / `assertComponentSnapshot` or equivalent)
- a project **URL helper** (e.g. `getUrl(path)`)
- an existing spec for a similar feature/page in `integrations/specs/` — copy its shape

---

## When to Use This Skill

- User wants to **write**, **add**, or **create** integration test(s) for a **page, URL, or flow**
  in a repo using `@blibli/integration-test-tools` v2.
- **Minimum input:** User shares the **URL** (or path) of the page to test, or names an existing
  flow/feature to extend. You then:
  - Resolve how to load that page (project helper like `getUrl(path)` or full URL with `host.name`).
  - Infer or discover what can be interacted with (buttons, links, modals); prefer existing specs
    or locators.
  - Write a **minimal** spec: load page → optionally click → assert outcome.
- **Clicks that lead to navigation:** Use `disableNavigation(page)` from
  `@blibli/integration-test-tools/lib/utils/navigation` in `beforeAll` after `page.goto(...)`.
- **Toast-producing actions:** follow the [toast checklist](#toast-checklist--use-whenever-an-action-can-trigger-a-toast).
- User just wants to **run** the existing integration suite (no new/changed spec) — delegate
  straight to [Running the tests](#running-the-tests), do not write or modify any `.spec.js` file.

**Do NOT use for:** Unit tests, E2E tests outside Playwright/blibli tooling, or non-UI integration
tests.

---

## Step 0b — Check for UI documentation

Look for `documentation/` folder at repo root (output of `create-ui-documentation` skill).

- Found → read doc for page/flow under test before writing spec. Confirms page behavior,
  components, state instead of guessing from code.
- Not found → run `create-ui-documentation` skill first to generate it, then continue.

---

## Quick Start

1. **Version gate** passes (v2.x installed).
2. **Step 0**: discover this repo's helpers, locator file, setup helpers, mock-generators, snapshot wrapper.
3. **Step 0b**: `documentation/` folder exists → read relevant doc. Missing → run
   `create-ui-documentation` skill first, then continue.
4. **Get URL/flow** from user; resolve with this repo's URL helper if present, else `host.name` + port.
5. **Inspect existing specs** under `integrations/specs/` for the same feature or a similar page:
   locators, setup helpers, mocks, viewport.
6. **Create or extend spec:** One `describe`, `beforeAll` — use this repo's setup helper if
   present, else viewport → goto → disableNavigation (if needed) → waitForNetworkIdle → optional
   stopAnimations; then tests (load + assert, click + assert, toast + assert, or
   failure/variant flows). Scroll before a component snapshot when the element is below the fold.
7. **Run:** see [Running the tests](#running-the-tests) below; update snapshots if needed (e.g.
   `npm run integration:updateSnapshot`) only after visually confirming the new baseline.

---

## Running the tests

Delegate to the `run-integration-test` skill (from the `ui-integration-test` plugin) for running,
diagnosing, auto-mocking, and flow-traversing the suite. Don't reimplement that logic here.

- **Skill available** → invoke `run-integration-test`, done.
- **Skill not found** → tell user to install it first, then stop:

  ```
  /plugin marketplace add gdncomm/agent-plugins
  /plugin install ui-integration-test@agent-plugins
  ```

---

## Spec skeleton

Adjust the import paths/alias (`@integrations/helpers/...` vs `@integrations/utils/...` vs a
relative path) and the exported helper names to whatever Step 0 found in this repo.

```javascript
const responsive = require('@blibli/integration-test-tools/lib/utils/responsive')
const host = require('@blibli/integration-test-tools/lib/utils/host')
const networkUtil = require('@blibli/integration-test-tools/lib/utils/network')
const { mockSetTimeout, verifyToast, /* whatever this repo's reset fn is called */ } = require('<this repo's toast helper path>')
const { assertContentSnapshot } = require('<this repo's snapshot helper path>')
const locator = require('<this repo's locator file path>')
// + whichever setup helper this repo's general-setup/fixtures module exposes for this feature

const TARGET_HOST = host.name + ':<port>' // check the feature's actual port in the project's integration-test config

describe('<Flow name>', () => {
  beforeAll(async () => {
    await responsive.setDesktop(page, { height: 900 }) // or responsive.setMobile(page)
    // call the relevant setup helper here, plus any $blibli.mock.update overrides
    await page.goto(`https://${TARGET_HOST}/<path>`)
    await networkUtil.waitForNetworkIdle(page, 1000, 1)
  })

  // assertion focus: <one line describing what this test proves>
  test('1. <step>', async () => {
    await page.locator(locator.someLocator).waitFor()
    await assertContentSnapshot(expect, page)
  })
})
```

Every `test()` should carry a one-line `// assertion focus:` comment above it (matches existing
specs in most of these repos) stating what the test proves — not what it clicks. A spec file can
re-mock mid-file (call the mock setup helper again with a different response) to cover a second
scenario in the same `describe` block, rather than duplicating the whole file.

Every `test()` description must start with a capital letter (e.g. `test('1. Should show toast')`,
not `test('1. should show toast')`).

---

## Toast checklist — use whenever an action can trigger a toast

Toasts across these apps are timer-driven (`window.setTimeout`), so tests must fake the timer
before triggering the action, or the toast auto-dismisses before Playwright can see it. The
three-step shape is the same everywhere; only the cleanup function's **name** varies per repo (see
Step 0's table). Full detail and edge cases (multi-toast, absence assertions,
`assertToastDlsText`-style helpers) are in
[patterns/modal-and-toast.md](patterns/modal-and-toast.md).

```javascript
const { mockSetTimeout, verifyToast, verifyMultipleToast } = require('<toast helper path>')
// import whichever cleanup fn this repo actually exports:
// resetTimeoutAndRemoveToast | resetTimeoutAndHideToast | resetTimeoutAndHideToastOld
const { resetTimeoutAndRemoveToast } = require('<toast helper path>')

test('N. <action that shows a toast>', async () => {
  await mockSetTimeout(page)          // 1. stub window.setTimeout BEFORE the triggering click
  await page.locator(locator.xxxButton).click()
  await verifyToast(page)             // 2. wait for '.blu-toast' (pass a selector for a scoped toast)
  await assertContentSnapshot(expect, page)
  await resetTimeoutAndRemoveToast(page) // 3. always clean up, even on failure paths — flushes
                                          //    pending timeouts and removes the toast node so it
                                          //    doesn't leak into the next test's snapshot
})
```

- Use `verifyMultipleToast(page, count)` instead of `verifyToast` when an action can stack more
  than one toast (not every repo exports this — check Step 0).
- The reset/cleanup function is mandatory at the end of any test that called `mockSetTimeout` —
  skipping it leaks the stubbed `setTimeout` and stale toast DOM into subsequent tests in the same
  file.
- If the toast should NOT appear (e.g. asserting an error path fails silently), still call
  `mockSetTimeout` before the action for consistency, but assert absence with
  `page.locator('.blu-toast').waitFor({ state: 'hidden' })` instead of `verifyToast`.

---

## Redirection checklist — use whenever an action navigates/redirects the page

In the test/mock environment, real navigation is stubbed: instead of actually changing
`window.location`, the app's redirect helper (e.g. `pyeongyang-ui-member`'s
`vue3/src/util/test-helper.js` — `goUrl` / `replaceLocation`) sets `window.customUrl` to the
target URL and returns early, so Playwright can assert on the intended destination without the
page actually navigating away. Check Step 0 for this repo's equivalent helper and exported name —
don't assume `customUrl` if the repo names it differently.

```javascript
test('N. <action that redirects>', async () => {
  await page.locator(locator.xxxButton).click()
  await page.waitForFunction(() => window.customUrl) // wait for the redirect helper to set it
  const customUrl = await page.evaluate(() => window.customUrl)
  expect(customUrl).toBe(`https://${TARGET_HOST}/<expected-path>`)
})
```

- Always assert the **full expected URL** (including query params, e.g. a `ref=` redirect-back
  URL), not just that a redirect happened.
- Use `page.waitForFunction(() => window.customUrl)` before reading it when the redirect isn't
  guaranteed to have happened synchronously by the time of the assertion (e.g. after an async
  validation call); skip the wait only when the preceding action is already awaited and
  synchronous.

---

## Other kinds of helpers to look for and reuse

These are the categories that recur across repos using this tooling — confirm exact names/paths
via Step 0 rather than assuming any of the below:

| Helper category | Typical purpose |
|---|---|
| Feature/page setup helpers (e.g. `setupXxxPage`, `runXxxSetUp`, `setupDesktopFirstFold`) | Bundle the common `$blibli.mock.update` calls a page/feature needs, or bundle viewport+goto+wait, so specs don't repeat them |
| Snapshot helper (`assertContentSnapshot`, `assertComponentSnapshot` or similar) | Full-page vs scoped-selector visual snapshot assertions |
| Locator file | Central map of CSS selectors / `data-testid`s; add new selectors here rather than inlining strings in a spec |
| Mock-generators / fixtures | Canned response-body builders for domain entities (address, member, security, etc.) — extend these before hand-rolling response bodies |
| mockUtils / feature-config helpers | Toggle feature flags or product config for a test |
| Tracker/dataLayer helpers | Asserting GTM/analytics events fired (e.g. `filterFromDataLayer`, `clearDataLayer`) |
| Redirect helper (e.g. `goUrl`/`replaceLocation` in `test-helper.js`) | Stubbed navigation that sets `window.customUrl` (or repo equivalent) instead of really navigating — see [Redirection checklist](#redirection-checklist--use-whenever-an-action-navigatesredirects-the-page) |
| Init-script helpers | Tests needing custom `window.*` flags set via `context.addInitScript` before the page loads |
| Delay/scroll helpers (`generateDelay`, `scrollToSelector`) | Stability after scroll or variant switch, and scrolling below-the-fold elements into view before a component snapshot |
| Shared constants | Timeout/wait-time constants — don't hardcode magic numbers if the repo already has one |

---

## Writing new helper functions

When this repo has no existing helper to reuse (e.g. a new mock-generator or setup helper), and
you write one for the spec:

- **Don't add unused parameters.** Only include a parameter the function body actually reads.
- **Prefer a destructured object parameter over positional arguments**, so callers are
  self-documenting and argument order doesn't matter:

  ```javascript
  // Avoid
  const buildAddress = (id, name, isDefault) => ({ id, name, isDefault })

  // Prefer
  const buildAddress = ({ id, name, isDefault }) => ({ id, name, isDefault })
  ```

- **When a value is mandatory, or overridden by many callers, give it its own named parameter**
  instead of folding it into a catch-all `otherOverrides`/`options` bag:

  ```javascript
  // Avoid — isDefault is set by nearly every caller but hidden inside otherOverrides
  const buildAddress = ({ id, otherOverrides = {} }) => ({ id, ...otherOverrides })

  // Prefer — mandatory/commonly-overridden fields are explicit, named parameters
  const buildAddress = ({ id, isDefault, name }) => ({ id, isDefault, name })
  ```

  Reserve a generic `otherOverrides`/`options` bag for genuinely optional, rarely-set fields.

---

## Pattern Files

| File | When to use |
|------|-------------|
| [patterns/url-first-minimal.md](patterns/url-first-minimal.md) | Minimal spec from URL: load, disable nav, click, assert |
| [patterns/desktop-mobile.md](patterns/desktop-mobile.md) | Viewport and responsive utils (desktop vs mobile) |
| [patterns/modal-and-toast.md](patterns/modal-and-toast.md) | Testing modals, toasts, and overlays — including the toast checklist in full detail |
| [patterns/scroll-delay-and-setup.md](patterns/scroll-delay-and-setup.md) | Project setup helpers, scroll before snapshot, generateDelay, variant switching |
| [patterns/mocks-and-failure-states.md](patterns/mocks-and-failure-states.md) | API mocks (`$blibli.mock.update`), feature config, testing failure/error states |

---

## References

| Reference | Content |
|-----------|---------|
| [references/navigation.md](references/navigation.md) | `disableNavigation`, `handleClickOpenNewTab` |
| [references/snapshot.md](references/snapshot.md) | `assertSnapshot`, `assertComponentSnapshot`, baselines |
| [references/url-and-host.md](references/url-and-host.md) | `host.name`, project `getUrl` |
| [references/project-setup-helpers.md](references/project-setup-helpers.md) | How to detect and use this repo's setup helpers |
| [references/blibli-tools-utils.md](references/blibli-tools-utils.md) | Overview of all `@blibli/integration-test-tools` utils |
| [references/tool-documentation.md](references/tool-documentation.md) | Canonical `@blibli/integration-test-tools` doc — config schema, util functions, mock/snapshot APIs, changelog. Source of truth over Confluence. |

---

## Decision Guide

### Where to put the spec file

| Case | Location |
|------|----------|
| New page, no existing spec | `integrations/specs/<feature>/<page>/desktop/<Name>.spec.js` (or `mobile/`) |
| Same page, new flow | Add to existing spec file |
| Mobile variant | `integrations/specs/<feature>/<page>/mobile/<Name>.spec.js` |

### Which pattern to follow

| Scenario | Pattern |
|----------|---------|
| "Test this URL" / minimal page test | [url-first-minimal](patterns/url-first-minimal.md) |
| Desktop vs mobile | [desktop-mobile](patterns/desktop-mobile.md) |
| Modal / toast | [modal-and-toast](patterns/modal-and-toast.md) |
| This repo has setupDesktopFirstFold / scroll / variant | [scroll-delay-and-setup](patterns/scroll-delay-and-setup.md) |
| Mock API or test error state | [mocks-and-failure-states](patterns/mocks-and-failure-states.md) |

---

## Implementation Checklist

- [ ] **Version gate passed:** `@blibli/integration-test-tools` is v2.x. If v3+, stopped and redirected user.
- [ ] **Step 0 done:** found this repo's toast helper, locator file, setup helpers, mock-generators, snapshot wrapper — and their actual exported names.
- [ ] **Step 0b done:** `documentation/` folder checked — read if present, generated via `create-ui-documentation` skill if missing.
- [ ] User provided URL/path or named an existing flow; resolved how to open it.
- [ ] Checked for existing spec; create new or extend.
- [ ] **Setup:** Use this repo's setup helper if present, else viewport → goto → disableNavigation (if needed) → waitForNetworkIdle.
- [ ] Imports use this repo's actual helper paths/names, not another repo's.
- [ ] **Mocks:** If testing failure or stable API, set `$blibli.mock.update` and/or feature-config helper before navigation.
- [ ] **Toast:** Any toast-producing action wrapped with `mockSetTimeout` → trigger → `verifyToast` → this repo's cleanup fn.
- [ ] **Redirection:** Any navigating/redirecting action asserts the full expected URL via this repo's redirect helper (e.g. `window.customUrl`), not just that navigation happened.
- [ ] For component snapshot below the fold: scroll to selector (and optional delay) before `assertComponentSnapshot`.
- [ ] At least one test: load + assert; at least one: click + assert, variant + assert, toast + assert, or failure assert.
- [ ] Every `test()` description starts with a capital letter.
- [ ] New selectors added to this repo's locator file, not inlined.
- [ ] New mock-generator/helper params are only added if a spec actually calls them with a value — no speculative `otherOverrides`/options bags added "just in case." Before finalizing a new helper, grep its call sites to confirm.
- [ ] Ran per [Running the tests](#running-the-tests): `integration:prepare` first if this is a collab repo, `test` script added if missing; update snapshots only after visually confirming the new baseline is correct.

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Test navigates away on click | Link/button triggers navigation | Add `await disableNavigation(page)` in beforeAll after goto |
| Toast never appears / times out | `mockSetTimeout` not called before the triggering action, or toast already auto-dismissed | Call `mockSetTimeout(page)` immediately before the click, then `verifyToast(page)` |
| Later tests see a leftover toast or stubbed timer | Skipped the cleanup fn after a toast test | Always call this repo's reset/cleanup fn (`resetTimeoutAndRemoveToast` or equivalent) at the end of the test |
| Snapshot mismatch | UI or baseline changed | Run snapshot update command |
| Timeout on goto | Wrong URL/port or app not running | Verify URL/port against the project's integration-test config and dev server |
| Element not found | Selector or timing | Use `waitFor()` before click/assert; prefer this repo's locator file |
| Flaky animation | Animations in progress | Add `await animationUtil.stopAnimations(page)` after load |
| Snapshot crops wrong area | Element below the fold | Scroll to selector before `assertComponentSnapshot` |
| Need stable/failure API | Real API varies | Use `$blibli.mock.update`; see [mocks-and-failure-states](patterns/mocks-and-failure-states.md) |
| Imported a helper that doesn't exist in this repo | Copied import from another repo/spec without re-checking | Re-run [Step 0](#step-0--discover-this-repos-helpers-before-writing-anything) for this repo |
