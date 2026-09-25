# Pattern: Desktop and Mobile Viewports

Use when the spec must run in a specific viewport (desktop or mobile) or when adding both desktop
and mobile variants.

---

## When to use

- User asks for "desktop" or "mobile" test.
- This repo's spec layout has `integrations/specs/<feature>/<page>/desktop/` and `mobile/`.

---

## Util

```javascript
const responsive = require('@blibli/integration-test-tools/lib/utils/responsive')

await responsive.setDesktop(page)
await responsive.setMobile(page)
```

Use in `beforeAll` **before** `page.goto(...)`.

---

## File layout

| Viewport | Typical path |
|----------|----------------|
| Desktop | `integrations/specs/<feature>/<page>/desktop/<Name>.spec.js` |
| Mobile | `integrations/specs/<feature>/<page>/mobile/<Name>.spec.js` |

When a flow differs by viewport (e.g. a mobile-only back button, or a desktop-only two-column
layout), mirror the scenario in both folders rather than special-casing one file.

---

## See also

- [url-first-minimal.md](url-first-minimal.md)
- [references/blibli-tools-utils.md](../references/blibli-tools-utils.md)
