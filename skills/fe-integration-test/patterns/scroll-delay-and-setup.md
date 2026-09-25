# Pattern: Scroll, Delay, and Project Setup Helpers

Use when this repo provides **setup helpers** (e.g. `setupDesktopFirstFold`) or when you need
**scroll-into-view** before a component snapshot and **delays** for stability.

---

## When to use

- **Setup helpers:** You see `setupDesktopFirstFold(page, { url })` (or similarly-named) in other
  specs in this repo — use it instead of raw viewport + goto + wait.
- **Component snapshot:** The target element is below the fold; scroll it into view before
  `assertComponentSnapshot`.
- **Stability:** After scroll or variant change, use a short/long delay so the UI settles.

---

## Project setup helpers

Path and name vary per repo — confirm via
[Step 0 in SKILL.md](../SKILL.md#step-0--discover-this-repos-helpers-before-writing-anything).

```javascript
const { setupDesktopFirstFold } = require('<this repo's setup helper path>')
const { getUrl } = require('<this repo's url helper path>')

beforeAll(async () => {
  await setupDesktopFirstFold(page, {
    url: getUrl('/p/product-slug/is--item-sku')
  })
  await animationUtil.stopAnimations(page)
})
```

See [references/project-setup-helpers.md](../references/project-setup-helpers.md).

---

## Scroll before component snapshot

```javascript
const utils = require('<this repo's utils path>')
await page.locator(selector).waitFor()
await utils.scrollToSelector(page, selector, utils.DESKTOP_ADJUSTMENT)
await delay.short()
await snapshotUtil.assertComponentSnapshot({ expect, page, selector, options })
```

---

## generateDelay

Not every repo has this — check Step 0 before assuming it exists; a plain
`await page.waitForTimeout(ms)` is an acceptable fallback if it doesn't.

```javascript
const generateDelay = require('<this repo's delay helper path>')
const delay = generateDelay(page)
await delay.short()
await delay.long()
```

---

## Variant switching

```javascript
await page.click(productVariantsSection.secondVariant)
await someElement.waitFor()
await utils.scrollToSelector(page, locator.someElement, utils.DESKTOP_ADJUSTMENT)
await delay.short()
await snapshotUtil.assertComponentSnapshot({ ... })
```

---

## See also

- [references/project-setup-helpers.md](../references/project-setup-helpers.md)
- [mocks-and-failure-states.md](mocks-and-failure-states.md)
