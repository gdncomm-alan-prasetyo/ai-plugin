# Pattern: API Mocks and Failure States

Use when the spec needs to **control API responses** (`$blibli.mock.update`) or **feature flags**
(a project mock-utils module), or when testing **error/failure states**.

---

## When to use

- Page depends on **backend APIs** and you need a stable or error response.
- You need to **toggle feature flags** or product config for the test.
- You want a **failure spec**: mock APIs to fail, then assert fallback or component gone.

---

## $blibli.mock.update (API response)

Global across all repos using this tooling — no per-repo variance here.

```javascript
$blibli.mock.update({
  method: 'GET',
  url: '/backend/.../some-path',
  status: 200,
  response: { code: 200, status: 'OK', data: { ... } }
})
```

- **Failure path:** Set `status: 500` and an error response. Page may show fallback or hide a
  section.
- **Path params:** Some repos support `param_values` alongside `url` to match a parameterized
  route (e.g. `param_values: { addressId: 'Bdg' }`).
- Call at **describe level** or inside **beforeAll** before `page.goto`, or mid-test (before the
  action that triggers the request) when a later test in the same file needs a different response.

---

## Response-body fixtures / generators

Before hand-rolling a response body inline, check whether this repo has a mock-generators/fixtures
module (path varies — see
[Step 0 in SKILL.md](../SKILL.md#step-0--discover-this-repos-helpers-before-writing-anything)) with
canned entities for the domain (address, member, security, etc.) and reuse/extend those instead.

```javascript
const { addresses } = require('<this repo's mock-generators path>/address')
$blibli.mock.update({ url: '/backend/...', method: 'GET', status: 200, response: { data: [addresses.default] } })
```

---

## mockUtils (feature / product config)

Not every repo has this — confirm the actual module path/name via Step 0.

```javascript
const mockUtils = require('<this repo's mock-utils path>')

mockUtils.updateProductConfigs([
  { id: 'enableSomeFeature', value: 'false' }
])
```

---

## Testing failure state

1. Mock APIs to fail (`status: 500`) in `beforeAll` before navigation, or mid-test before the
   action that triggers the request.
2. Trigger the request (load the page, or click the button that calls it).
3. **Assert fallback:** Component snapshot of the area that stays visible, or a toast if this
   repo surfaces server errors via toast (see [modal-and-toast.md](modal-and-toast.md)).
4. **Assert element gone:** `await page.locator(selector).waitFor({ state: 'detached' })` then
   `expect(await page.locator(selector).isVisible()).toBeFalsy()`.

---

## See also

- [scroll-delay-and-setup.md](scroll-delay-and-setup.md)
- [modal-and-toast.md](modal-and-toast.md)
- [references/blibli-tools-utils.md](../references/blibli-tools-utils.md)
