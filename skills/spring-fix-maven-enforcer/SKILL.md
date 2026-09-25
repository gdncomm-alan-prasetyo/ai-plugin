---
name: spring-fix-maven-enforcer
description: Fixes GDN Jenkins CI's Maven Enforcer plugin violations — dependencyConvergence, banDuplicatePomDependencyVersions, banDistributionManagement, reactorModuleConvergence, banDynamicVersions, bannedDependencies, bannedPlugins, bannedRepositories, requireJavaVendor. Use when a Jenkins build fails with "Failed to execute goal ... maven-enforcer-plugin ... enforce", or when asked to fix an enforcer/dependency-convergence/banned-dependency/banned-plugin error. Reference: https://gdncomm.atlassian.net/wiki/spaces/GDNIT/pages/716865679/Enforce+Maven+Project+Best+Practices
---

# Spring — Fix Maven Enforcer Violations

## Model Guidance

Capable-tier. First output line: `[spring-fix-maven-enforcer] running on: {model} (capable-tier)`

---

## Background

GDN enforces Maven project hygiene via `maven-enforcer-plugin:3.5.0` in Jenkins CI. Rules checked **serially** (rule 0 → rule n) — a build fails on the first violated rule, so fixing one rule then re-running often surfaces the next. Plan for multiple iterations, don't expect one commit to clear every rule.

Source config (authoritative, current): `gdncomm/jenkins-ci-automation` → `resources/maven/gdn/enforcer.xml`.

---

## Step 1 — Identify the Failed Rule

Read the Jenkins/Maven error output. It names the rule and gives a `Rule N: org.apache.maven.enforcer.rules.*` class. Match against Step 2's table, then apply that rule's fix.

---

## Step 2 — Rules and Fixes

### Ban Distribution Management

Project must not declare a `<distributionManagement>` section — Jenkins CI manages releasability itself.

**Fix**: delete the entire `<distributionManagement>` block from `pom.xml`.

### Dependency Convergence

Same dependency (`groupId:artifactId`) resolves to **different versions** via different paths in the reactor (e.g. one module pulls `feign-core:9.5.0` directly, another pulls it transitively at `11.8` through `feign-okhttp`).

**Fix**: pick the one correct version, declare it **once** in the parent pom's `<dependencyManagement>`, and remove any inline `<version>` on that dependency from every child pom — they inherit from the managed version instead. This is the same BOM-first principle as `spring-fix-trivy-vulnerability`: one managed version, no scattered overrides.

### Ban Duplicate Pom Dependency Versions

A dependency's version is declared in a child pom when it's **already managed** in the parent's `<dependencyManagement>`.

**Fix**: remove the redundant `<version>` from the child — inherit from the parent instead. Version lives in exactly one place.

### Reactor Module Convergence

Multi-module project: one module depends on another module in the *same reactor* at a version that doesn't match the reactor's actual current version (e.g. `module-b` still points at `module-a:1.2.0` when the reactor's `module-a` is now `1.3.0-SNAPSHOT`).

**Fix**: point inter-module dependencies at `${project.version}` (or the parent's version property) instead of a hardcoded literal, so they always track the reactor.

### Ban Dynamic Versions

No version ranges, `LATEST`, `RELEASE`, or anything requiring Maven to resolve at build time. `allowSnapshots: true` — `-SNAPSHOT` versions are permitted.

**Fix**: pin to one specific released version.

### Banned Dependencies

Company-wide exclude list — some entries need a version bump, some need complete removal/replacement. Current list (`resources/maven/gdn/enforcer.xml`):

| Dependency (excluded range) | Action |
|---|---|
| `org.apache.logging.log4j:log4j-core:[,2.17.1)` | Upgrade to ≥ 2.17.1 |
| `org.apache.commons:commons-configuration2:[2.4.0,2.8.0)` | Upgrade to ≥ 2.8.0 |
| `org.apache.commons:commons-text:[1.5,1.10.0)` | Upgrade to ≥ 1.10.0 |
| `org.projectlombok:lombok:[,1.18.30)` | Upgrade to ≥ 1.18.30 |
| `org.postgresql:postgresql:[,42.6.0)` | Upgrade to ≥ 42.6.0 |
| `org.redisson:redisson:[3.0.0,3.34.1)` | Upgrade to ≥ 3.34.1 |
| `commons-logging:commons-logging:[,1.3.5)` | Upgrade to ≥ 1.3.5 — or better, exclude it entirely and use SLF4J/Log4j2 directly (Spring's own guidance: commons-logging is only for the framework's internal use, not application code) |
| `org.apache.httpcomponents.client5:httpclient5:[5.0,5.4)` | Upgrade to ≥ 5.4 (virtual-thread support) |
| `org.apache.httpcomponents.core5:httpcore5:[5.0,5.3)` | Upgrade to ≥ 5.3 |
| `org.apache.tomcat.embed:tomcat-embed-{core,jasper,websocket,el}:[9.0.0,9.0.79)` | Upgrade to ≥ 9.0.79 |
| `org.apache.tomcat.embed:tomcat-embed-{core,jasper,websocket,el}:[10.1.0,10.1.12)` | Upgrade to ≥ 10.1.12 |
| `org.mongodb:{mongodb-driver-sync,mongodb-driver-reactivestreams,mongodb-driver-core,bson}:[,4.11.5)` | Upgrade to ≥ 4.11.5 |
| `com.blibli.oss:blibli-backend-framework-newrelic` | Remove entirely — no replacement listed |
| `org.json:json` | Remove entirely |
| `com.itextpdf:itextpdf` | Remove entirely |
| `org.mongodb:mongodb-driver-async` | Remove — legacy async driver, migrate to `mongodb-driver-reactivestreams` |
| `org.mongodb:mongodb-driver` | Remove — legacy driver, migrate to `mongodb-driver-sync` + `mongodb-driver-core` + `bson` |
| `org.mongodb:mongo-java-driver` | Remove — legacy driver, same migration as above |
| `com.rabbitmq:amqp-client` | Remove entirely — no replacement listed, check current messaging stack (Kafka?) |

**Fix procedure**: same BOM-first principle applies — if the excluded dependency's group publishes a BOM, bump the BOM (see `spring-fix-trivy-vulnerability`). Otherwise pin the specific fixed version directly in `<dependencyManagement>`. For "remove entirely" entries, delete the dependency and find/implement the replacement — don't just silence the rule.

### Banned Plugins

| Plugin (excluded range) | Action |
|---|---|
| `org.jacoco:jacoco-maven-plugin:[,0.8.11)` | Upgrade to ≥ 0.8.11 |
| `org.apache.maven.plugins:maven-deploy-plugin:[,3.1.3)` | Upgrade to ≥ 3.1.3 |

### Banned Repositories

`https://artifactory.gdn-app.com/*` is banned as both a `<repository>` and `<pluginRepository>` source.

**Fix**: remove that repository URL from `pom.xml`'s `<repositories>`/`<pluginRepositories>`; use the approved dependency source instead.

### Require Java Vendor

JDK vendor must be one of: `Eclipse Adoptium`, `GraalVM Community`, `Alpine`, `Debian`, `IcedTea`.

**Fix**: not a pom.xml fix — check the build/CI JDK image is one of the approved vendors. Flag to the user rather than silently editing infra config.

---

## Step 3 — Reproduce and Verify Locally

Rules run serially — expect to iterate.

1. Add the enforcer plugin config to the project's parent `pom.xml` (copy the `<plugin>` block from `gdncomm/jenkins-ci-automation` → `resources/maven/gdn/enforcer.xml` — do not hand-retype the banned-dependency list, always pull the current version, it changes over time).
2. Run (ask before executing): `mvn org.apache.maven.plugins:maven-enforcer-plugin:3.5.0:enforce`
3. Fix the first reported rule, re-run, repeat until clean.

The exact CI validation command (subset of rules, matches Jenkins):
```shell
mvn org.apache.maven.plugins:maven-enforcer-plugin:3.5.0:enforce -Denforcer.rules=dependencyConvergence,banDuplicatePomDependencyVersions,banDistributionManagement,reactorModuleConvergence
```

---

## Return Format

```
ENF-{n} | {rule-name} | {file:line or dependency coordinate}
  problem: {what violated, why}
  fix: {concrete pom.xml change — Before/After for anything beyond a one-line version bump}
```

No violations found / all rules pass → `ENF: no findings.`

---

## Constraints

- **Don't guess fixed versions** — the banned-dependency/plugin tables above are current as of this skill's last sync with `gdncomm/jenkins-ci-automation`. If a version isn't listed or looks stale, fetch the live `resources/maven/gdn/enforcer.xml` rather than assume.
- **BOM-first for convergence fixes** — same principle as `spring-fix-maven-enforcer`'s sibling skill `spring-fix-trivy-vulnerability`: prefer a BOM version bump over scattered singular overrides when a BOM exists.
- **Don't run builds without asking** — same as other BE skills in this repo.
- **"Remove entirely" entries need a real replacement, not just deletion** — deleting a dependency that's actually used without migrating the calling code just trades one build failure for a compile failure.
