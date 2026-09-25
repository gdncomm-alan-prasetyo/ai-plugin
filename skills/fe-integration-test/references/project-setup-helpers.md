# Project Setup Helpers

Many projects bundle **viewport + navigation + wait conditions**, or **common API mocks**, into a
single setup function. Names, paths, and exact behavior vary per repo — always confirm via
[Step 0](../SKILL.md#step-0--discover-this-repos-helpers-before-writing-anything) rather than
assuming the examples below exist verbatim.

---

## Why use them

- **Consistency:** Same viewport, goto, and wait rules (or same base mocks) across specs.
- **Less duplication:** No need to repeat setDesktop → goto → waitForNetworkIdle →
  resolveAllLazyComponent, or repeat the same `$blibli.mock.update` calls, in every spec.

---

## How to detect

Search under this repo's `integrations/` tree (helpers or utils folder — path varies) for names
like `setupDesktop`, `setupMobile`, `setup.*FirstFold`, `runXxxSetUp`, `setupXxxPage`, or a
`require('@integrations/.../setup')`-style import in existing specs.

```bash
grep -rEl "setup[A-Z][A-Za-z]*\(|runFullyQualified" --include='*.spec.js' --include='*.js' integrations/ 2>/dev/null
```

---

## Two flavors seen across repos

**1. Page-load setup** (viewport + goto + wait), e.g.:

```javascript
await setupDesktopFirstFold(page, { url: getUrl(path) })
```

First argument: `page`. Second: options with at least `url`. Afterward, specs often add
`animationUtil.stopAnimations(page)`, a chat-widget hider, or `disableNavigation(page)`.

**2. Mock/fixture setup** (bundles the `$blibli.mock.update` calls a feature needs), e.g.:

```javascript
runAddressModuleListSetUp([addresses.default, addresses.complete])
```

Called in `beforeAll` before `page.goto(...)`; extend this kind of helper (or add a sibling
function) rather than duplicating the same set of mocks across specs testing the same feature.

---

## When not to use

- No setup helper in this repo: use manual beforeAll (viewport → goto → waitForNetworkIdle) as in
  [url-first-minimal](../patterns/url-first-minimal.md), and inline `$blibli.mock.update` calls
  directly (only extract into a shared helper once 2+ specs need the same mocks).

---

## Related

- [scroll-delay-and-setup](../patterns/scroll-delay-and-setup.md)
- [mocks-and-failure-states](../patterns/mocks-and-failure-states.md)
- [url-first-minimal](../patterns/url-first-minimal.md)
