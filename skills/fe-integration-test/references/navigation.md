# Navigation Utils (@blibli/integration-test-tools)

**Source:** `@blibli/integration-test-tools/lib/utils/navigation` — package path, stable across repos.

---

## disableNavigation(page)

Prevents the page from navigating when the user (or test) clicks links or buttons that would
trigger navigation. Uses the Navigation API to call `event.preventDefault()`.

**When to use:** Page has external links (e.g. share, social) or buttons that navigate to another
route, and the test wants to assert an in-page effect (modal, toast) without leaving the page.

**Usage:**

```javascript
const { disableNavigation } = require('@blibli/integration-test-tools/lib/utils/navigation')

beforeAll(async () => {
  await page.goto(url, { waitUntil: 'load', timeout: 60000 })
  await disableNavigation(page)
  await networkUtil.waitForNetworkIdle(page, 1000, 1)
})
```

Call **after** `page.goto(...)`.

---

## handleClickOpenNewTab(page, selector)

Clicks an element that would open a new tab, waits for the popup, then closes it.

---

## Related

- [url-first-minimal](../patterns/url-first-minimal.md)
- [SKILL.md](../SKILL.md)
