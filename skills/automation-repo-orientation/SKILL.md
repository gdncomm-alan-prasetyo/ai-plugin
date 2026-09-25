---
name: automation-repo-orientation
description: Checks a QA Cucumber/Selenium automation repo (under ~/Data/Automation/GDN/) for an existing CLAUDE.md. Found → read it, done. Missing → explores the repo and writes a comprehensive AI-oriented CLAUDE.md (tech stack, structure, domain concepts, test strategy, message flow, AI notes). Invoked by qa-automation/qa-jenkins-check/qa-check before digging into a failed scenario or running locally, so repo structure doesn't get re-explored from scratch every run.
---

# Automation Repo Orientation

## Model Guidance

Fast-tier. First output line: `[automation-repo-orientation] running on: {model} (fast-tier)`

Exploration + fixed-template writeup — cheapest capable model is fine, same reasoning as `repo-orientation`.

---

## Core Rule

Read-only except the one write: creating `CLAUDE.md` at the automation repo's root. No other file touched, no test run, no build.

---

## Step 1 — Check for Existing CLAUDE.md

Glob `{repo_path}/CLAUDE.md`.

- **Exists** → read, hold as background context, return to caller. Regenerate only if caller explicitly says it looks stale (repo structure changed materially since doc stopped matching reality).
- **Missing** → Step 2.

## Step 2 — Explore the Repo

Confirmed structure for repos under `~/Data/Automation/GDN/` (Maven + Cucumber): `pom.xml`, `Jenkinsfile*`, `src/main/java/...`, `src/test/java/.../module/api/{service}/{steps,hooks}`, `src/test/resources/features/{1_integration_test,2_sanity_test,3_regression_test}/`, `src/test/resources/templates/`.

Gather, don't assume — read what's actually there:
- `pom.xml` — artifactId, parent, key dependencies (Cucumber, RestAssured/Selenium, DB drivers, Kafka client if present)
- `Jenkinsfile*` — build/run parameters, environments referenced (e.g. `UATB`, `PREPROD` config classpaths)
- `src/test/java/.../module/api/{service}/` — steps, hooks, any page objects / request builders / client wrappers
- `src/test/resources/features/*/` — one `.feature` file per test type folder, tags used (`@Sanity`, `@Regression`, `@Integration`, `@TestSuiteId=...`)
- `src/test/resources/templates/` — request/response templates, what they model
- Any `application*.properties`/`.yml` under `src/test/resources` — config per environment
- README.md if present — don't duplicate it, note anything CLAUDE.md-relevant it's missing

## Step 3 — Write CLAUDE.md

Use this exact template. Audience is AI coding assistants, not humans — dense, no marketing language, bullets over paragraphs. Never invent information — mark a section `Unknown` if it can't be inferred from the repo. Mermaid diagrams where genuinely useful (e.g. request lifecycle, message flow). Code snippets only when they clarify architecture, not for their own sake.

```markdown
# Tech Stack
- Programming language
- Frameworks
- Build tools
- Database
- Messaging systems
- External integrations
- Testing frameworks

# Repository Structure
Each major package/module and its responsibility.

# Core Business Concepts
Important domain objects and business terminology.

# Key Components
Important classes/services:
- Controllers
- Services
- Repositories
- Kafka Consumers
- Kafka Producers
- Scheduled Jobs
- Event Models
- Utilities

# External Dependencies
External systems and how this service interacts with them.

# Configuration
Important application properties and environment variables.

# Message Flow
Kafka topics/events: producer topics, consumer topics, payload purpose, retry mechanism, DLQ behavior (if any).

# Database
Main tables, relationships, frequently accessed entities.

# Request Lifecycle
Step-by-step example from receiving a request until completion.

# Error Handling
Exception hierarchy, retry logic, logging strategy, monitoring.

# Coding Conventions
Naming, package organization, DTO vs Entity usage, mapper usage, Optional usage, null handling, logging, validation.

# Testing Strategy
- Total Scenario Test — Regression, Integration, and Sanity, by tag
- Environment: UATB and PREPROD

# Common Development Tasks
- Add a new REST endpoint
- Add a Kafka consumer
- Add a Kafka producer
- Add a database table

# Important Files
pom.xml, application.yml, docker-compose.yml, Jenkinsfile, README.md, Kubernetes manifests.

# AI Notes
- Files that should not be modified unless necessary
- Existing design patterns to follow
- Preferred coding style
- Common pitfalls
- Business rules that must never be violated
```

Test-automation repo, not service under test — sections like Controllers/Kafka Producers/Database may genuinely not apply (repo calls those, doesn't own them). Mark `Unknown` or `N/A — this repo is a test client, not the service` rather than forcing content. Testing Strategy and Repository Structure/Key Components (steps, hooks, page objects, feature folders) most likely to have real, repo-specific content — don't shortchange those.

Write the file to `{repo_path}/CLAUDE.md`. New file, no fenced markers, no upsert dance — this repo has no prior auto-generated block to merge with.

## Step 4 — Return

Confirm to caller: path written, one-line summary of what's in it. Caller reads it next as background context before touching feature files/step defs.

---

## Constraints

- Never invent information — `Unknown` beats a guess, every time.
- Don't duplicate an existing README — reference it, don't restate it.
- Read-only except the single `CLAUDE.md` write. No test/build run, no edits elsewhere in the repo.
- Regenerate only when caller says the existing doc looks stale — never on a hunch.
