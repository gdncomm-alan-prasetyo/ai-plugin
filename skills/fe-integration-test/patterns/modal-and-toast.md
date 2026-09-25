# Pattern: Modal and Toast Assertions

Use when the test clicks a button or link and expects a **modal** (dialog/overlay) or **toast**
message.

---

## When to use

- Click opens a **modal** (e.g. confirmation dialog, size chart, share, report).
- Click triggers a **toast** (e.g. success, error message).

---

## Modal: wait and assert visible

```javascript
await page.locator(buttonSelector).click()
await page.locator(modalSelector).waitFor()
expect(await page.locator(modalSelector).isVisible()).toBeTruthy()
```

---

## Modal: component snapshot

```javascript
await page.locator(buttonSelector).click()
await page.locator(modalSelector).waitFor()
await snapshotUtil.assertComponentSnapshot({
  expect,
  page,
  selector: modalSelector,
  options: { assertConfig: FAILURE_THRESHOLD }
})
```

---

## Toast: fake the timer, verify, clean up

Toasts across these apps are timer-driven (`window.setTimeout`), so a test that triggers one must
stub the timer **before** the triggering action, or the toast auto-dismisses before Playwright can
observe it. Confirm this repo's actual helper first — see
[Step 0 in SKILL.md](../SKILL.md#step-0--discover-this-repos-helpers-before-writing-anything) —
the three-step shape below is consistent, but the cleanup function's **name** varies per repo
(`resetTimeoutAndRemoveToast`, `resetTimeoutAndHideToast`, `resetTimeoutAndHideToastOld`, etc.).

```javascript
const { mockSetTimeout, verifyToast } = require('<this repo's toast helper path>')
const { resetTimeoutAndRemoveToast } = require('<this repo's toast helper path>') // name varies — see Step 0

test('N. <action that shows a toast>', async () => {
  await mockSetTimeout(page)          // 1. stub window.setTimeout BEFORE the triggering click
  await page.locator(buttonSelector).click()
  await verifyToast(page)             // 2. wait for '.blu-toast' (pass a selector for a scoped toast)
  await assertContentSnapshot(expect, page) // or snapshotUtil.assertSnapshot(expect, page)
  await resetTimeoutAndRemoveToast(page) // 3. always clean up, even on failure paths — flushes
                                          //    pending timeouts and removes the toast node so it
                                          //    doesn't leak into the next test's snapshot
})
```

- Use `verifyMultipleToast(page, count)` instead of `verifyToast` when an action can stack more
  than one toast (not every repo exports this).
- The reset/cleanup function is **mandatory** at the end of any test that called
  `mockSetTimeout` — skipping it leaks the stubbed `setTimeout` and stale toast DOM into
  subsequent tests in the same file.
- If the toast should **not** appear (e.g. asserting an error path fails silently), still call
  `mockSetTimeout` before the action for consistency, but assert absence with
  `page.locator('.blu-toast').waitFor({ state: 'hidden' })` instead of `verifyToast`.
- Some repos instead expose a combined assertion like `assertToastDlsText('Expected message')`
  that waits for network idle and checks the toast's text directly — prefer that when present
  instead of a bare `verifyToast` + snapshot.

---

## See also

- [references/snapshot.md](../references/snapshot.md)
- [url-first-minimal.md](url-first-minimal.md)
