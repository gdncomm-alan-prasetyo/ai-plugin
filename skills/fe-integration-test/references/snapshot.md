# Snapshot Utils (@blibli/integration-test-tools)

**Source:** `@blibli/integration-test-tools/lib/utils/snapshot` — package path, stable across repos.
Most repos also wrap it in a project-local helper (e.g. `assertContentSnapshot`,
`assertComponentSnapshot` in `integrations/helpers/snapshot.js` or similar) that pins a shared
`failureThreshold`/`failureThresholdType`. Prefer that wrapper — found via
[Step 0](../SKILL.md#step-0--discover-this-repos-helpers-before-writing-anything) — over calling
`snapshotUtil` directly, unless this repo has no such wrapper.

---

## assertSnapshot(expect, page, options?)

Full-page screenshot vs baseline. Use for "load well" or full-page visual regression.

```javascript
await snapshotUtil.assertSnapshot(expect, page)
```

---

## assertComponentSnapshot({ expect, page, selector, options? })

Screenshot of a single element (e.g. modal, section) vs baseline.

```javascript
await snapshotUtil.assertComponentSnapshot({
  expect,
  page,
  selector: '.blu-modal',
  options: { assertConfig: FAILURE_THRESHOLD }
})
```

---

## Baselines

Stored in `__image_snapshots__/` next to the spec. First run or after UI changes: run the
project's snapshot update command (e.g. `npm run integration:updateSnapshot`).

---

## Related

- [modal-and-toast](../patterns/modal-and-toast.md)
- [url-first-minimal](../patterns/url-first-minimal.md)
