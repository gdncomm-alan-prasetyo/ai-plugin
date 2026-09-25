# URL and Host

**Source:** `@blibli/integration-test-tools/lib/utils/host` — package path, stable across repos.

---

## host.name

Use `host.name` for the host part of any URL. Do **not** hardcode `localhost`; when the browser
runs in Docker, the app may be reached via `host.docker.internal`.

```javascript
const host = require('@blibli/integration-test-tools/lib/utils/host')
const url = 'http://' + host.name + ':8081/path'
```

Check the actual port for the feature you're testing in the project's integration-test config
(e.g. `blibli-integration-test.config.cjs`) — ports differ per app/module within a repo.

---

## Project URL helpers

Many repos define a project-local helper that wraps `host.name` and the correct port. Prefer that
when [Step 0](../SKILL.md#step-0--discover-this-repos-helpers-before-writing-anything) finds one.

```javascript
const { getUrl } = require('@integrations/utils') // path varies per repo — confirm via Step 0
await page.goto(getUrl('/p/product-slug/ps--SKU'))
```

---

## Related

- [url-first-minimal](../patterns/url-first-minimal.md)
- [SKILL.md](../SKILL.md)
