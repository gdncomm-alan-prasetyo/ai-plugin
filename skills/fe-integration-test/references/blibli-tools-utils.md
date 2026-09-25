# @blibli/integration-test-tools — Utils Overview

Quick reference for utils from `@blibli/integration-test-tools/lib/utils/`. These import paths are
the npm package's own API and are stable across every repo using this tooling (unlike the
project-local helpers under `integrations/helpers` or `integrations/utils`, which vary — see
[Step 0 in SKILL.md](../SKILL.md#step-0--discover-this-repos-helpers-before-writing-anything)).

---

## responsive

`responsive.setDesktop(page)` | `responsive.setMobile(page)` — viewport. Use before goto.

---

## network

`networkUtil.waitForNetworkIdle(page, 1000, 1)` — after goto.

---

## snapshot

`snapshotUtil.assertSnapshot(expect, page)` — full page.
`snapshotUtil.assertComponentSnapshot({ expect, page, selector, options })` — single element.

Most repos wrap these in a project-local helper (e.g. `assertContentSnapshot`) that pins shared
`failureThreshold` options — prefer that wrapper when Step 0 finds one instead of calling
`snapshotUtil` directly.

---

## animation

`animationUtil.stopAnimations(page)` — reduce flakiness after load.

---

## host

`host.name` — host for URLs (no hardcoded localhost). Use in all test URLs.

---

## navigation

`disableNavigation(page)` — after goto when page has navigation-leading clicks.
`handleClickOpenNewTab(page, selector)` — click that opens new tab; wait for popup and close.

---

## interaction (optional)

Use when you need structured click/type helpers beyond `page.locator(...).click()`.
