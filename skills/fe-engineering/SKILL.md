---
name: fe-engineering
description: Builds production-quality Vue 3 UIs for IAM frontend repos using BLUE 3 design system (`@blibli/blue.*` components, `@blibli/blue-design-tokens`). Use when creating or refactoring `.vue` views/components, layouts, modals, styling (SCSS), accessibility, or reducing complexity while keeping UI on-brand.
---

# Vue UI Engineering (IAM)

## Overview

Ship UI accessible, performant, visually consistent with Blibli's BLUE design system — not generic "AI UI." Prefer simple code paths: small components, extracted logic, early returns, low cognitive complexity.

IAM Vue repos mix conventions — Options API vs Composition API, Pinia vs Vuex, colocated vs flat `js/` split. Check target repo's neighboring files before applying a rule below — match what's there, not what's "ideal."

## When to Use

- New or updated pages under `src/pages/` — or `vue3/src/pages/` if repo has a `vue3/` folder
- New or updated components under `src/components/` — or `vue3/src/components/` if repo has a `vue3/` folder
- Responsive behavior, loading/error/empty states, modals
- Refactors aiming for simpler templates, scripts, styles — same product intent

Check repo root first. `vue3/` folder present → repo mid vue2-to-vue3 migration, new Vue 3 work lives under `vue3/src/`, not plain `src/` (plain `src/` stays legacy Vue 2).

## Step 0 — Read Repo Docs

Read `CLAUDE.md` at repo root first. Contains repo-specific context — stack, conventions, scripts, known gotchas — often with its own doc steps or links to further docs. Follow those steps, build context fast, skip re-discovering repo from scratch.

Skip step if `CLAUDE.md` missing.

## Stack (verify per repo)

| Area | Use |
|------|-----|
| UI | Vue 3 SFCs. IAM repos lean **Options API** (`export default { data, methods, components }` in split `js/*.js` file) — new code matches neighboring files; `<script setup>` ok for fresh, isolated component, no existing pattern to match |
| Design system | **BLUE 3** — per-component packages `@blibli/blue.<name>` (`blue.modal`, `blue.button`, `blue.badge`, `blue.field`, etc), icons via `@blibli/blue-dls-library-icon`, helpers via `@blibli/blue-dls-utils`, font via `@blibli/blue-font` |
| Tokens | `@blibli/blue-design-tokens` — direct `$blu-*` variables, no alias layer |
| Build | Vite |
| Styles | `lang="scss"` scoped |
| State | **Pinia** (`defineStore`, `src/stores/*.js`) and/or **Vuex 4** — check `package.json` and `src/stores` before assuming either |
| Router | `vue-router` |
| i18n | `vue-i18n`, `$t()` in templates, strings in `src/i18n/locale/*.json` |

**Legacy BLUE 2 warning:** some IAM repos mid-migration, still carry `@blibli/dls`, `@blibli/blue-tokens`, `@blibli/blue-supports`, `@blibli/blue-icon` (BLUE 2) alongside BLUE 3 packages. New code targets BLUE 3 only. Never mix BLUE 2 and BLUE 3 component packages inside one component.

## Code Simplification (non-negotiable)

- **One responsibility per component** — split data-fetching, mapping, heavy markup into separate concerns if one `.vue` does all three.
- **Extract logic** into the split `js/*.js` file (Options API) or a composable (Composition API) — match repo convention.
- **Early returns** for loading/error/empty branches — avoid deep `if/else` nesting in methods or `setup`.
- **Keep methods/functions small** — move branches into named helpers.
- **Declarative template** over imperative DOM — `v-if`/`v-for` + computed over manual DOM patches in `mounted`.
- **No prop drilling past ~3 levels** — use provide/inject or store instead.

## Component Architecture

### Colocation (observed pattern)

```
src/components/<feature>/
  ComponentName.vue      # template + <style scoped> only
  js/
    component-name.js    # <script src="./js/component-name.js">, Options API export default
```

Some repos flatten `js/` per component **type** instead of per feature — one shared `src/components/js/` folder for all components in that directory. Match whichever pattern the target folder already uses — don't introduce a third pattern mid-repo.

Pages follow the same split: `src/pages/PageName.vue` + `src/pages/js/page-name.js`.

### Import pattern for BLUE 3 components

```js
import BliModal from '@blibli/blue.modal/dist/modal/blue/Modal'
import BliModalHeader from '@blibli/blue.modal/dist/modal/blue/ModalHeader'
import BliModalBody from '@blibli/blue.modal/dist/modal/blue/ModalBody'

export default {
  name: 'ExampleModal',
  components: { BliModal, BliModalHeader, BliModalBody }
}
```

Exact subpath (`dist/modal/blue/Modal`) varies per package — check the package's own `dist/` folder or an existing import of the same package elsewhere in the repo before guessing a new path.

### Container vs presentation

- **Container** — fetch, store, router, error handling. Returns early with skeleton/error/empty.
- **Presentation** — props in, emits out, minimal side effects.

### Composition over configuration

Prefer slots over a component with dozens of props controlling all copy and layout.

## State: pick the smallest thing that works

| Need | Direction |
|------|-----------|
| UI-only (open tab, hover) | Local `data()` / `ref` |
| Shared by a few siblings | Lift state or a small shared method/composable |
| Cross-route or many consumers | Pinia store (`src/stores/*.js`) or Vuex module — match what the repo already uses |
| Filters, deep links | `vue-router` query params |
| Server data | Existing `src/api/*.js` layer — don't duplicate fetch logic in components |

## Design System Adherence

### Tokens — direct, no alias layer

IAM projects import `@blibli/blue-design-tokens` directly. No `bliket-alias-tokens.scss`-style indirection layer — use `$blu-*` variables as-is.

```scss
<style lang="scss" scoped>
@import '~@blibli/blue-design-tokens/dist/tokens-default.scss';
@import '~@blibli/blue-dls-utils/dist/scss/blue-helper';  // mixins, e.g. @include mobile { ... }
</style>
```

Tilde (`~`) import resolves through the project's Vite/sass config. If migrating to Vite 8, tilde imports break — see `vite-8-ui-migration` skill.

### Spacing (`$blu-spacing-*`)

| px | Token |
|----|-------|
| 0 | `$blu-spacing-zero` |
| 1 | `$blu-spacing-3xs` |
| 2 | `$blu-spacing-2xs` |
| 4 | `$blu-spacing-xs` |
| 8 | `$blu-spacing-s` |
| 12 | `$blu-spacing-ms` |
| 16 | `$blu-spacing-m` |
| 20 | `$blu-spacing-ls` |
| 24 | `$blu-spacing-l` |
| 32 | `$blu-spacing-xl` |
| 36 | `$blu-spacing-2xls` |
| 40 | `$blu-spacing-2xl` |
| 48 | `$blu-spacing-3xl` |
| 56 | `$blu-spacing-4xl` |
| 64 | `$blu-spacing-5xl` |
| 72 | `$blu-spacing-6xl` |

### Border radius (`$blu-border-radius-*`)

Same scale as spacing, plus `$blu-border-radius-circle: 50%`.

### Colors — direct `$blu-color-*`, no aliasing

| Role | Token |
|------|-------|
| Primary text | `$blu-color-neutral-text-high` |
| Secondary text | `$blu-color-neutral-text-med` |
| Low-emphasis text | `$blu-color-neutral-text-low` |
| Disabled text | `$blu-color-neutral-text-disabled` |
| Inverted text (on dark bg) | `$blu-color-neutral-text-inv` |
| Default icon | `$blu-color-neutral-icon-default` |
| Disabled icon | `$blu-color-neutral-icon-disabled` |
| Default border | `$blu-color-neutral-border-default` |
| Divider / low border | `$blu-color-neutral-border-low` |
| Info (brand) | `$blu-color-brand-info-background-default` / `-text-default` / `-icon-default` / `-border-default` |
| Danger | `$blu-color-brand-danger-background-default` |
| Success | `$blu-color-brand-success-background-default` |
| Alert | `$blu-color-brand-alert-background-default` |

Never use raw hex. If a Figma value has no token match, flag it and confirm with design before hardcoding.

### Typography (`$blu-text-*`, composite font shorthand)

| Style | Token | Value |
|-------|-------|-------|
| Headline 1 | `$blu-text-headline-1` | 600 40px/48px |
| Headline 2 | `$blu-text-headline-2` | 600 32px/38px |
| Headline 3 | `$blu-text-headline-3` | 600 24px/28px |
| Title 1 | `$blu-text-title-1` | 600 20px/24px |
| Title 2 | `$blu-text-title-2` | 600 18px/24px |
| Subtitle 1 | `$blu-text-subtitle-1` | 600 16px/20px |
| Subtitle 2 | `$blu-text-subtitle-2` | 600 14px/18px |
| Body 1 | `$blu-text-body-1` | 500 16px/20px |
| Body 2 | `$blu-text-body-2` | 500 14px/18px |
| Label | `$blu-text-label` | 600 12px/16px |
| Caption 1 | `$blu-text-caption-1` | 500 12px/16px |
| Caption 2 | `$blu-text-caption-2` | 500 10px/14px |

Usage: `font: $blu-text-body-1;`

### Shadow / elevation

| Token | Value |
|-------|-------|
| `$blu-shadow-default` | `0 1px 6px 0 #0000001A` |
| `$blu-shadow-med` | `0 2px 12px 0 #00000033` |
| `$blu-elevation-default` | same as shadow-default, dark-bg-safe |
| `$blu-elevation-med` | same as shadow-med, dark-bg-safe |

### Avoid the "AI aesthetic"

| Avoid | Prefer |
|-------|--------|
| Generic purple/indigo palettes | `$blu-color-*` tokens |
| Heavy gradients, giant radii | Flat or subtle, match existing pages |
| Uniform card grids, no hierarchy | Layout driven by content |
| Lorem-only copy | Realistic copy / real i18n keys |
| Huge padding everywhere | Spacing consistent with nearby components |

### Class naming

BEM-style, matches observed repos: `.component-name__element`, modifiers `.component-name--state`.

## Accessibility (WCAG 2.1 AA mindset)

- Native controls (`button`, `a`, `input`) — keyboard/focus work by default.
- Icon-only controls: `aria-label`.
- Labels associated with inputs.
- Modals: focus management + escape via BLUE modal's built-in behavior — don't hand-roll.
- Meaningful empty/error states (`role="status"` or heading + text), never a blank region.

## Responsive Behavior

Mobile-first. Verify roughly 320px, 768px, 1024px, 1440px when touching layout.

## Loading and Feedback

Prefer BLUE skeleton/loader components (`@blibli/blue.loader-skeleton`, `@blibli/blue.loader-general`) over custom spinners where the codebase already uses them for similar lists/cards.

## Red Flags

- `.vue`/split `js` file over ~200 lines with no split plan
- Deep template nesting — extract subcomponent
- Raw hex/px values instead of `$blu-*` tokens
- Missing loading/error/empty state for user-triggered fetches
- Color as the only signal for state — pair with text or icon
- Mixing BLUE 2 (`@blibli/dls`) and BLUE 3 (`@blibli/blue.*`) components in one file

## Verification Checklist

- [ ] No new console errors
- [ ] Keyboard: tab order sensible, actions trigger on Enter/Space where expected
- [ ] Loading, error, empty paths covered for new async UI
- [ ] SCSS uses `$blu-*` tokens — no raw hex/px
- [ ] New UI matches adjacent screens (BLUE 3 components only, no legacy mixing)
- [ ] Unit/integration test impact considered (Vitest / Playwright/Jest per repo)

## Related Project Guidance

- For merge-ready review criteria, use the `fe-code-reviewer` agent once added.
- For debugging failures, use the `fe-debug` skill.
