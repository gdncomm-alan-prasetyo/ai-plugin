# Pattern: URL-First Minimal Spec

Use when the user provides only a **URL** (or path) and you need a minimal integration spec: load
page, optionally prevent navigation, click, and assert.

---

## When to use

- User says: "Write integration test for this URL", "Add integration test for this page", or
  shares a URL/path only.
- Goal: Minimal coverage — page loads and at least one interaction (click) with an assertion.

---

## Flow

1. Resolve **test URL** from user input (path or full URL).
2. Resolve **how to open** it: this repo's `getUrl(path)`-style helper if
   [Step 0](../SKILL.md#step-0--discover-this-repos-helpers-before-writing-anything) found one,
   else `'http://' + host.name + ':PORT' + path`.
3. Decide **one or more interactions**: prefer this repo's locator file or a similar existing
   spec; else use role/text/selector.
4. If the page has **links/buttons that navigate**, use `disableNavigation(page)` in `beforeAll`.

---

## Imports

```javascript
const responsive = require('@blibli/integration-test-tools/lib/utils/responsive')
const networkUtil = require('@blibli/integration-test-tools/lib/utils/network')
const snapshotUtil = require('@blibli/integration-test-tools/lib/utils/snapshot') // or this repo's snapshot wrapper
const animationUtil = require('@blibli/integration-test-tools/lib/utils/animation')
const host = require('@blibli/integration-test-tools/lib/utils/host')
const { disableNavigation } = require('@blibli/integration-test-tools/lib/utils/navigation')
```

---

## beforeAll

```javascript
beforeAll(async () => {
  await responsive.setDesktop(page)
  await page.goto(url, { waitUntil: 'load', timeout: 60000 })
  await disableNavigation(page)
  await networkUtil.waitForNetworkIdle(page, 1000, 1)
  await animationUtil.stopAnimations(page)
})
```

Use this repo's URL helper for `url` when available. Omit `disableNavigation` only if the page has
no links/buttons that would navigate.

---

## Tests (minimal)

**1. Load + assert**

```javascript
test('1. should load well', async () => {
  await snapshotUtil.assertSnapshot(expect, page)
})
```

**2. Click + assert**

```javascript
test('2. should open modal when clicking button', async () => {
  await page.locator('button:has-text("Open")').click()
  await page.locator('.blu-modal').waitFor()
  expect(await page.locator('.blu-modal').isVisible()).toBeTruthy()
})
```

---

## See also

- [references/navigation.md](../references/navigation.md)
- [references/url-and-host.md](../references/url-and-host.md)
- [desktop-mobile.md](desktop-mobile.md)
- [modal-and-toast.md](modal-and-toast.md)
