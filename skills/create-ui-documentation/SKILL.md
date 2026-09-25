---
name: create-ui-documentation
description: >-
  Generates a documentation/ folder for a frontend (Vue/React) project — one
  doc per page and component, plus router, state-store, and architecture
  overviews, tied together by a README index. Use when asked to document a
  UI repo, generate frontend docs, or create a documentation folder for a
  Vue/React project.
---

# Create UI Documentation

## Purpose

Generate a `documentation/` folder for a frontend repo: one short doc per page/view and per reusable component, plus a router doc, a state-store doc, an architecture doc, and a README that indexes all of it.

**Golden rule: keep every doc simple.** A doc explains what code doesn't say for free — non-obvious behavior, why something is built the way it is, how pieces connect. It never restates what a reader gets from opening the file (don't describe every line, don't list every import). If a section would just repeat the code, cut it.

---

## Step 0 — Detect the Stack

Read `package.json` and skim the root folder to determine:

- Framework: Vue 2, Vue 3, React
- Router: Vue Router / React Router / none
- State management: Pinia, Vuex, Redux, Zustand, none
- Whether this is a standalone app or a micro-frontend (mounted into a parent shell, exposes/consumes globals, uses Module Federation, etc.)
- Whether the real source lives at `src/` directly, or under a nested folder (e.g. a migration left a parallel tree like `vue3/src/`) — check for a bootstrap-only `src/` that just imports from elsewhere before assuming `src/` is the app.

If none of this resolves cleanly, ask the user which framework/stack this is before proceeding.

---

## Step 1 — Map the Source Tree

Find and note:

- The real application root (pages/views, components, store, router, api/services, utils)
- Path aliases (`vite.config.*`, `jsconfig.json`, `tsconfig.json`, webpack config)
- Any convention where a `.vue`/`.jsx` file's logic lives in a sibling file (e.g. `Foo.vue` + `js/foo.js`) rather than inline — check before assuming a component's logic is empty
- Build setup: single build vs. multiple targets (e.g. desktop/mobile), and how each entry bootstraps the app
- Integration points with anything outside this repo: a parent shell app, shared globals (`window.*`), postMessage contracts, iframes/widgets loaded from other packages

---

## Step 2 — Enumerate Pages and Components

List every page/view file and every reusable component file. Group components by subfolder if the repo already groups them (e.g. `components/profile/`).

---

## Step 3 — Write One Doc Per Page

For each page, write `documentation/pages/<PageName>.md`:

```markdown
# <PageName>

File: `<path>` (+ sibling logic file if applicable)

Route: `<route-name>` — path `<path-or-config-key>` — <auth requirement, if any>

## Purpose

<1-3 sentences: what this page does and why it exists>

## Behavior

<Only non-obvious behavior: what it fetches/dispatches on mount, what it delegates to
a child widget/module, any guard or redirect logic, anything a reader wouldn't guess
from the template alone. Skip this section if there's nothing non-obvious.>

## Related

- <links to stores/components/router docs it depends on>
```

Skip empty sections rather than filling them with filler text.

---

## Step 4 — Write One Doc Per Component

For each component, write `documentation/components/<ComponentName>.md`:

```markdown
# <ComponentName>

File: `<path>` (+ sibling logic file if applicable)

## Purpose

<1-2 sentences: what it renders and where it's used>

## Props

| Prop | Type | Default | Notes |
|---|---|---|---|

(Omit table if the component takes no props.)

## Events

<emitted events, or "None" if it manages its own side effects internally>

## Behavior

<Only non-obvious logic — computed values with real logic behind them, side effects,
external calls. Skip trivial computed/props passthrough.>

## Used by

- <pages/components that use this>
```

---

## Step 5 — Write the Router Doc

`documentation/router.md` — only if the project has a router:

- One table: path, route name, component, auth/guard requirements, notes
- Navigation guards (`beforeEach`/`afterEach` or equivalent): what each guard checks and what it does on failure
- Where route paths come from if not hardcoded (e.g. a config file)

---

## Step 6 — Write the State/Store Doc

`documentation/stores.md` — only if the project has Pinia/Vuex/Redux/etc.:

- One short section per store/slice: state, key getters/actions, what consumes it
- Skip obvious getter/setter pairs; call out anything with real logic (derived state, side effects, cross-store coordination)

---

## Step 7 — Write the Architecture Doc

`documentation/architecture.md` — the system-level view, covering only what a new engineer would need explained to them (not what they'd read in 30 seconds of `ls`):

- Folder layout, with a one-line purpose per top-level folder
- Build setup (entry points, multiple build targets if any, path aliases)
- Integration contracts with anything outside the repo (parent shell, shared globals, widgets, postMessage) — this is usually the highest-value section
- Design system / component library in use
- Testing and CI setup (test runner, integration test tool, pipeline)

---

## Step 8 — Write the README Index

`documentation/README.md`:

- 2-4 sentence project summary (what it is, what part of the product it owns)
- Tech stack bullet list
- "Where the app actually lives" note, if Step 1 found a non-obvious source root
- Links to architecture.md, router.md, stores.md
- A table linking to every page doc, and every component doc
- A "CI / Code Quality" section with Jenkins and Sonar links (see below)

### CI / Code Quality section

Check `Jenkinsfile`, existing `README.md`, `sonar-project.properties`, `pom.xml`/`package.json` for Jenkins job URL and Sonar project key/URL first. Neither found → ask user for Jenkins URL and Sonar URL before writing section. No guessing, no placeholders.

Format:

```markdown
### CI / Code Quality
Jenkins :  
<jenkins-job-url>

Sonar :  
<sonar-dashboard-url>
```

---

## Step 9 — Write Root CLAUDE.md

Write `CLAUDE.md` at project root (not inside `documentation/`). Points any AI agent at docs before it touches code, flags real source root if non-obvious.

Model: `pyeongyang-ui-member/CLAUDE.md`. 2 sections:

1. **"Read the docs before the code"** — states `documentation/` is canonical, up-to-date map of app (architecture, router, stores, one doc per page/component). Tells agent: check it before exploring source or making any change. Numbered path: `documentation/README.md` for index, then page/component doc for specific work, then architecture.md/router.md/stores.md for cross-cutting concerns. Fallback line: grep codebase broadly only for things docs don't cover, or where code and docs disagree (mismatch may be the bug itself).
2. **"Where the code actually lives"** — include only if Step 1 found non-obvious source root (e.g. real app under `vue3/src/`, top-level `src/` just bootstrap shim). States real root, names file-split convention if any (e.g. `Foo.vue` pairs with `js/foo.js`), tells agent to check companion file for actual behavior.

Skip section 2 if source root unsurprising (plain `src/`, no split convention).

Template:

```markdown
# <project-name>

## Read the docs before the code

This repo has a `documentation/` folder that is the canonical, up-to-date map of the app: architecture, router, stores, and one doc per page/component. Before exploring source or making any change (feature work or debugging), check it first:

1. Start at [documentation/README.md](./documentation/README.md) for the doc index.
2. For a specific page or component, read its doc under `documentation/pages/` or `documentation/components/`.
3. For cross-cutting concerns (build/deploy, routing, state), read `documentation/architecture.md`, `documentation/router.md`, or `documentation/stores.md`.

Only fall back to grepping the codebase broadly for things the docs don't cover, or where code and docs disagree (that mismatch may itself be the bug).

## Where the code actually lives

<Only if Step 1 found a non-obvious source root. State the real root, the bootstrap-only decoy if any, and any file-split convention (e.g. `Page.vue` → `js/page.js`) so the agent checks the companion file for real behavior.>
```

If root `CLAUDE.md` already exists, merge these 2 sections in rather than overwrite unrelated content.

---

## Constraints

- **No filler.** Every doc should be readable in under a minute. If a section has nothing non-obvious to say, delete the section — don't pad it.
- **Don't restate the code.** Describe behavior and intent, not syntax.
- **Cross-link, don't duplicate.** If a page's behavior is fully explained in a store doc, link to it instead of repeating.
- **Skip sections that don't apply** to this project's stack (e.g. no stores.md if there's no state library).
- Write everything to a `documentation/` folder at the project root — don't scatter docs elsewhere.
