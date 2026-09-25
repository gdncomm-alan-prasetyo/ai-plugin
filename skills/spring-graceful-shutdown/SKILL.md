---
name: spring-graceful-shutdown
description: >-
  Implements Spring Boot graceful shutdown for Kafka and/or Google PubSub in a
  multi-module Spring Boot service. Redis graceful shutdown is handled implicitly
  by server.shutdown=graceful (no dedicated code needed). Detects tech stack
  (WebFlux vs MVC, Redis, Kafka, PubSub), identifies target modules, presents a
  concrete change plan, waits for approval, then implements all changes including
  tests. Use when asked to add graceful shutdown, fix Lettuce CancellationException
  on rolling deploy, ensure in-flight Kafka messages finish before pod termination,
  or prevent Google PubSub messages from being redelivered on pod deletion.
---

# Spring Graceful Shutdown

Implements graceful shutdown for Spring Boot services with Redis and/or Kafka.

## Agent behavior

- **Always follow the Detection and Planning phases** before touching any file.
- **Do not** make any code or config changes until the user explicitly approves the plan.
- **Scope:** Only add graceful shutdown plumbing. Do not refactor existing code.
- **Never run** Maven or other build commands automatically. Suggest copy-paste commands instead.

---

## Background — what graceful shutdown fixes

Without `server.shutdown=graceful`, a SIGTERM (Kubernetes rolling deploy) causes the JVM to exit immediately, which:

- **Redis (Lettuce):** Tears down the connection pool mid-flight, cancelling in-progress commands → `java.util.concurrent.CancellationException` from `CommandWrapper.cancel()`.
- **Kafka:** Stops consumer threads abruptly, leaving the current message batch partially processed and un-committed → potential duplicate processing or data loss.

`server.shutdown=graceful` tells Spring to drain the web layer before shutdown. `spring.lifecycle.timeout-per-shutdown-phase` sets the drain window. For Kafka, `spring.kafka.listener.shutdown-timeout` gives the listener container time to finish its current record before stopping.

---

## Phase 1 — Detection

Run all checks in parallel. Read only what is needed.

### 1a — Web layer (WebFlux vs MVC)

```
grep pattern: spring-boot-starter-webflux|spring-boot-starter-web\b
path: (project root)
glob: **/pom.xml
output_mode: content
```

- `spring-boot-starter-webflux` found → **WebFlux (reactive)**
- `spring-boot-starter-web` found (without webflux) → **MVC (servlet)**
- Both → flag as unusual, note it, proceed treating it as WebFlux if webflux is in the app module

> **Note:** WebFlux vs MVC does not change the implementation — the same `GracefulShutdownProperties` and `GracefulShutdownContextLogger` are created regardless. The distinction is recorded in the report for operator awareness only.

### 1b — Redis presence

```
grep pattern: spring-boot-starter-data-redis
glob: **/pom.xml
output_mode: files_with_matches
```

Also check:
```
grep pattern: @Cacheable|redisTemplate|ReactiveRedisTemplate
path: src/main
glob: *.java
output_mode: files_with_matches
```

> **Note:** Redis graceful shutdown is handled **implicitly** by `server.shutdown=graceful` — Spring shuts down the Lettuce connection pool through the standard `Lifecycle` mechanism during the drain phase. No Redis-specific `SmartLifecycle` bean is needed. The detection result is included in the report for visibility only.

### 1c — Kafka presence

```
grep pattern: @KafkaListener
path: src/main
glob: *.java
output_mode: files_with_matches
```

List every file found — these are the listener classes that must finish cleanly.

### 1d — Existing graceful shutdown config

Check both `application*.properties` and `bootstrap*.properties`, as Spring Cloud Config projects may place shared config in `bootstrap.properties`:

```
grep pattern: server\.shutdown|spring\.lifecycle\.timeout-per-shutdown-phase|spring\.kafka\.listener\.shutdown-timeout
glob: **/application*.properties
output_mode: content
```

```
grep pattern: server\.shutdown|spring\.lifecycle\.timeout-per-shutdown-phase|spring\.kafka\.listener\.shutdown-timeout
glob: **/bootstrap*.properties
output_mode: content
```

If any of these are already set (in either file), note the current values and which file contains them. Do not overwrite without flagging it.

### 1e — Validation namespace

Before writing any code, check which validation namespace the project uses:

```
grep pattern: jakarta.validation|javax.validation
path: src/main
glob: *.java
output_mode: files_with_matches
head_limit: 5
```

- Any result containing `jakarta.validation` → **Spring Boot 3** — use `jakarta.validation.constraints.*` in `GracefulShutdownProperties`.
- Only `javax.validation` results → **Spring Boot 2** — use `javax.validation.constraints.*`.
- No results → check `pom.xml` for `spring-boot-starter-parent` version: `3.x` → `jakarta`, `2.x` → `javax`.

Record the decision: `VALIDATION_NAMESPACE = jakarta | javax`

### 1f — Module structure

Identify the following modules by scanning the root `pom.xml` for `<module>` entries:

| Role | Convention | Purpose |
|------|-----------|---------|
| Properties | `*-properties` | Place `GracefulShutdownProperties` here |
| Configuration | `*-configuration` | Place `GracefulShutdownContextLogger` here |
| App | `*-app` | Place property values in `application-dev.properties` |

For each candidate module, confirm the Java source root path:
```
src/main/java/<package>/<properties|configuration>/
```
Use the package from an existing class in that module (e.g., read one `.java` file there to extract the package).

### 1g — Google PubSub presence

```
grep pattern: PubSubInboundChannelAdapter
glob: **/*.java
output_mode: files_with_matches
```

If found:

1. **Locate the messaging helper** — find the class that dispatches messages and calls `.block()`:
   ```
   grep pattern: \.block\(\)
   glob: **/*.java
   output_mode: files_with_matches
   ```
   Read that file. Confirm it receives a `Message<?>`, deserializes the payload, calls a processor, then explicitly ACKs/NACKs via `BasicAcknowledgeablePubsubMessage`. This is the injection point for the tracker.

2. **Identify the conditional guard** — find the `@ConditionalOnProperty` value used on the `PubSubInboundChannelAdapter` beans:
   ```
   grep pattern: @ConditionalOnProperty.*PubSubInboundChannelAdapter
   glob: **/*.java
   output_mode: content
   ```
   Or read the config class that declares the adapters and note the `@ConditionalOnProperty(value = "...")` on the class or bean methods. The tracker must use the same guard.

3. **Identify the target module** — the module that contains the messaging helper is where `PubSubInflightTracker` will be created.

4. **Check if tracker already exists**:
   ```
   grep pattern: PubSubInflightTracker
   glob: **/*.java
   output_mode: files_with_matches
   ```
   If found, note its location and skip Phase 4g/4h.

Record: `PUBSUB_DETECTED = YES | NO`, `PUBSUB_CONDITIONAL_PROPERTY`, `PUBSUB_MESSAGING_HELPER_PATH`, `PUBSUB_MODULE`.

### 1h — Pre-existence check for main classes

Check whether `GracefulShutdownProperties` and `GracefulShutdownContextLogger` already exist in the project:

```
grep pattern: class GracefulShutdownProperties
glob: **/*.java
output_mode: files_with_matches
```

```
grep pattern: class GracefulShutdownContextLogger
glob: **/*.java
output_mode: files_with_matches
```

If either is found, note its path. Do not overwrite existing implementations — skip the corresponding file in Phase 4 and flag it in the report.

Record: `PROPERTIES_EXISTS = YES at <path> | NO`, `LOGGER_EXISTS = YES at <path> | NO`

---

## Phase 2 — Analysis Report

Print a report in this exact format before proposing any changes:

```
[spring-graceful-shutdown] Detection complete

TECH STACK
  Web layer  : WebFlux (reactive) / MVC (servlet)
              (note: no implementation difference — recorded for visibility)
  Redis      : YES — spring-boot-starter-data-redis-reactive in <module>
                     (handled implicitly by server.shutdown=graceful, no dedicated code)
             : NO — no Redis dependency found
  Kafka      : YES — @KafkaListener found in <n> file(s): <list>
             : NO — no @KafkaListener found
  PubSub     : YES — PubSubInboundChannelAdapter found in <module>
                     Messaging helper: <path>
                     Conditional guard: @ConditionalOnProperty(value = "<key>")
                     Tracker already exists: YES | NO
             : NO — no PubSubInboundChannelAdapter found

EXISTING GRACEFUL SHUTDOWN CONFIG
  server.shutdown                              : <value or NOT SET> (found in <file>)
  spring.lifecycle.timeout-per-shutdown-phase : <value or NOT SET> (found in <file>)
  spring.kafka.listener.shutdown-timeout      : <value or NOT SET> (found in <file>)

EXISTING CLASSES
  GracefulShutdownProperties    : FOUND at <path> (will skip) | NOT FOUND
  GracefulShutdownContextLogger : FOUND at <path> (will skip) | NOT FOUND

MODULE TARGETS
  GracefulShutdownProperties    → <relative path to .java file>  (if not already found)
  GracefulShutdownContextLogger → <relative path to .java file>  (if not already found)
  application-dev.properties    → <relative path>
  PubSubInflightTracker         → <relative path to .java file>  (if PubSub detected)
```

---

## Phase 3 — Change Plan

After the report, present the full list of proposed changes. Wait for explicit approval before proceeding.

Format each change as:

```
PROPOSED CHANGES

1. NEW FILE — <relative path>
   <one-line description>

2. NEW FILE — <relative path>
   <one-line description>

3. MODIFY — <relative path>
   Add the following properties:
     <property key> = <value>
     ...

4. MODIFY — <properties module pom.xml path>  (only if spring-boot-starter-validation is missing)
   Add dependency: spring-boot-starter-validation (no scope — production scope)
   Reason: GracefulShutdownProperties uses @Validated and JSR-303 constraints at runtime;
           validation API must be on the production classpath of the properties module.
   Note: Do NOT add this to the configuration module as test scope — the configuration module
         already receives it transitively (compile scope) from the properties module. A direct
         test-scope declaration would override that via Maven "nearest wins", making validation
         unavailable to any future production code in the configuration module.

5. NEW FILE — <test file path>
   <one-line description>

6. NEW FILE — <test file path>
   <one-line description>

→ Approve? Reply "yes" or "go" to implement, or describe any changes you want first.
```

The standard change set is:

| # | File | Condition |
|---|------|-----------|
| 1 | `GracefulShutdownProperties.java` in properties module | Only if class does not already exist |
| 2 | `GracefulShutdownContextLogger.java` in configuration module | Only if class does not already exist |
| 3 | Properties added to `application-dev.properties` | Always (only keys not already present) |
| 4 | `spring-boot-starter-validation` (no scope) in **properties** module pom | Only if missing |
| 5 | `GracefulShutdownPropertiesBindingTest.java` | Only if class was newly created (item 1) |
| 6 | `GracefulShutdownContextLoggerTest.java` | Only if class was newly created (item 2) |
| 7 | `PubSubInflightTracker.java` in PubSub module | Only if PubSub detected and tracker missing |
| 8 | Modify messaging helper — inject tracker, wrap handler body | Only if PubSub detected and tracker missing |
| 9 | `PubSubInflightTrackerTest.java` | Only if PubSub detected and tracker missing |
| 10 | Add `@Mock PubSubInflightTracker` to messaging helper test | Only if PubSub detected and tracker missing |

---

## Phase 4 — Implementation

Only proceed after explicit user approval ("yes", "go", or equivalent).

Implement all changes in order. Read each target file before editing.

### 4a — GracefulShutdownProperties

Skip this step if `GracefulShutdownProperties` was found in Phase 1h.

Create in the `-properties` module under the existing properties package.

Follow the package and annotation pattern of existing properties in that module:
- If existing classes use `@Component` + `@ConfigurationProperties` → use the same.
- If they use `@Configuration` + `@ConfigurationProperties` → use the same.
- Always add `@Validated`.
- Use the validation namespace detected in Phase 1e: `jakarta.validation.constraints.*` for Spring Boot 3, `javax.validation.constraints.*` for Spring Boot 2.

```java
package <same package as other properties classes>;

// Spring Boot 3:
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
// Spring Boot 2:
// import javax.validation.constraints.Max;
// import javax.validation.constraints.Min;
// import javax.validation.constraints.Pattern;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;
import org.springframework.validation.annotation.Validated;

@Data
@Validated
@Component
@ConfigurationProperties(prefix = "graceful.shutdown")
public class GracefulShutdownProperties {

  /**
   * Shutdown mode. "graceful" drains in-flight requests before shutdown;
   * "immediate" disables graceful shutdown.
   * Maps 1:1 to Spring's server.shutdown via placeholder in application.properties.
   */
  @Pattern(regexp = "graceful|immediate")
  private String mode = "graceful";

  /**
   * Maximum seconds to wait for in-flight requests/messages to complete.
   * Maps to spring.lifecycle.timeout-per-shutdown-phase and
   * spring.kafka.listener.shutdown-timeout via placeholder.
   */
  @Min(1)
  @Max(300)
  private int timeoutSeconds = 30;
}
```

### 4b — GracefulShutdownContextLogger

Skip this step if `GracefulShutdownContextLogger` was found in Phase 1h.

Create in the `-configuration` module under the existing configuration package.

**Design notes:**
- Implements `SmartLifecycle` with `getPhase() = Integer.MIN_VALUE` so its `stop()` runs **last** in the shutdown sequence — after the web server drain and Kafka listener drain have both completed. This gives operators a reliable "drain phase complete" signal.
- The `onApplicationEvent` guard `if (getParent() != null) return` prevents duplicate log lines in parent–child context topologies (e.g. if a child context is ever introduced alongside the root context).
- `ContextClosedEvent` fires at the **start** of `context.close()`, before `Lifecycle.stop()` is called on any `SmartLifecycle` bean — so the "drain phase starting" message is accurate.

```java
package <same package as other configuration classes>;

import java.util.Optional;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.ApplicationListener;
import org.springframework.context.SmartLifecycle;
import org.springframework.context.event.ContextClosedEvent;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
@Slf4j
@RequiredArgsConstructor
public class GracefulShutdownContextLogger
    implements ApplicationListener<ContextClosedEvent>, SmartLifecycle {

  private final Environment environment;
  private volatile boolean running = false;

  @Override
  public void onApplicationEvent(ContextClosedEvent event) {
    if (event.getApplicationContext().getParent() != null) {
      return;
    }
    log.info(
        "Graceful shutdown: drain phase starting application={} pod={} contextId={}",
        application(),
        pod(),
        event.getApplicationContext().getId());
  }

  @Override
  public void start() {
    running = true;
  }

  @Override
  public void stop() {
    log.info(
        "Graceful shutdown: drain phase complete application={} pod={}",
        application(),
        pod());
    running = false;
  }

  @Override
  public boolean isRunning() {
    return running;
  }

  @Override
  public int getPhase() {
    return Integer.MIN_VALUE;
  }

  private String application() {
    return environment.getProperty("spring.application.name", "unknown");
  }

  private String pod() {
    return Optional.ofNullable(System.getenv("HOSTNAME")).orElse("-");
  }
}
```

### 4c — application-dev.properties

Append to the existing `application-dev.properties`. Add a blank line before the block if the file does not already end with one.

Before appending, check which of the three keys already exist in the file (either in `application-dev.properties` or `bootstrap*.properties` as noted in Phase 1d). Only add keys that are not already set. If a key already exists, update its value to use the placeholder form instead of adding a duplicate.

**Always add (if not already present):**
```properties
# Graceful shutdown
graceful.shutdown.mode=graceful
graceful.shutdown.timeout-seconds=30
server.shutdown=${graceful.shutdown.mode}
spring.lifecycle.timeout-per-shutdown-phase=${graceful.shutdown.timeout-seconds}s
```

**If Kafka was detected (Phase 1c), also add (if not already present):**
```properties
spring.kafka.listener.shutdown-timeout=${graceful.shutdown.timeout-seconds}s
```

For each key that already exists:
- If its value already uses the placeholder form → leave it unchanged, note it in the summary.
- If its value is hardcoded → update it to use the placeholder form, note the change.

### 4d — pom.xml (properties module)

Only if `spring-boot-starter-validation` is not already a dependency: add it **without** a `<scope>` tag (defaults to `compile`) to the properties module's `pom.xml`. This puts `jakarta.validation-api` and Hibernate Validator on the production classpath so that `@Validated` constraint binding works at runtime.

Locate the `<dependencies>` block and insert before the closing `</dependencies>` tag:

```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-validation</artifactId>
</dependency>
```

### 4e — GracefulShutdownPropertiesBindingTest

Skip this step if `GracefulShutdownProperties` already existed (Phase 1h).

Create in the **`-properties` module** under `src/test/java/<package>` — same package as `GracefulShutdownProperties`:

```java
package <same package as GracefulShutdownProperties>;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.autoconfigure.context.ConfigurationPropertiesAutoConfiguration;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Configuration;

class GracefulShutdownPropertiesBindingTest {

  private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
      .withConfiguration(AutoConfigurations.of(ConfigurationPropertiesAutoConfiguration.class))
      .withUserConfiguration(TestConfiguration.class);

  @Test
  void shouldBindDefaultValues() {
    contextRunner.run(context -> {
      GracefulShutdownProperties props = context.getBean(GracefulShutdownProperties.class);
      assertThat(props.getMode()).isEqualTo("graceful");
      assertThat(props.getTimeoutSeconds()).isEqualTo(30);
    });
  }

  @Test
  void shouldBindCustomValues() {
    contextRunner
        .withPropertyValues(
            "graceful.shutdown.mode=immediate",
            "graceful.shutdown.timeout-seconds=60")
        .run(context -> {
          GracefulShutdownProperties props = context.getBean(GracefulShutdownProperties.class);
          assertThat(props.getMode()).isEqualTo("immediate");
          assertThat(props.getTimeoutSeconds()).isEqualTo(60);
        });
  }

  @Test
  void shouldRejectInvalidMode() {
    contextRunner
        .withPropertyValues("graceful.shutdown.mode=fast")
        .run(context -> assertThat(context).hasFailed());
  }

  @Test
  void shouldRejectZeroTimeout() {
    contextRunner
        .withPropertyValues("graceful.shutdown.timeout-seconds=0")
        .run(context -> assertThat(context).hasFailed());
  }

  @Test
  void shouldRejectExcessiveTimeout() {
    contextRunner
        .withPropertyValues("graceful.shutdown.timeout-seconds=301")
        .run(context -> assertThat(context).hasFailed());
  }

  @Configuration
  @EnableConfigurationProperties(GracefulShutdownProperties.class)
  static class TestConfiguration {
  }
}
```

### 4f — GracefulShutdownContextLoggerTest

Skip this step if `GracefulShutdownContextLogger` already existed (Phase 1h).

Create in the `-configuration` module under `src/test/java/<package>`.

**Coverage required:**
- Root-context close → logs "drain phase starting"
- Child-context close → no log (parent guard)
- HOSTNAME absent → pod falls back to "-"
- `SmartLifecycle.stop()` → logs "drain phase complete" + sets `isRunning()` to false
- `getPhase()` → returns `Integer.MIN_VALUE`

```java
package <same package as GracefulShutdownContextLogger>;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.context.event.ContextClosedEvent;
import org.springframework.context.support.GenericApplicationContext;
import org.springframework.core.env.Environment;

@ExtendWith(OutputCaptureExtension.class)
class GracefulShutdownContextLoggerTest {

  @Test
  void shouldLogApplicationNameAndPodOnContextClose(CapturedOutput output) {
    Environment env = mock(Environment.class);
    when(env.getProperty("spring.application.name", "unknown"))
        .thenReturn("test-service");

    GracefulShutdownContextLogger listener = new GracefulShutdownContextLogger(env);

    GenericApplicationContext ctx = new GenericApplicationContext();
    ctx.refresh();
    listener.onApplicationEvent(new ContextClosedEvent(ctx));
    ctx.close();

    assertThat(output.getAll()).contains("Graceful shutdown");
    assertThat(output.getAll()).contains("test-service");
  }

  @Test
  void shouldFallbackToDashWhenHostnameEnvAbsent(CapturedOutput output) {
    Environment env = mock(Environment.class);
    when(env.getProperty("spring.application.name", "unknown"))
        .thenReturn("unknown");

    GracefulShutdownContextLogger listener = new GracefulShutdownContextLogger(env);

    GenericApplicationContext ctx = new GenericApplicationContext();
    ctx.refresh();
    listener.onApplicationEvent(new ContextClosedEvent(ctx));
    ctx.close();

    assertThat(output.getAll()).containsPattern("pod=.+");
  }

  @Test
  void shouldNotLogWhenEventIsFromChildContext(CapturedOutput output) {
    Environment env = mock(Environment.class);
    when(env.getProperty("spring.application.name", "unknown"))
        .thenReturn("test-service");

    GracefulShutdownContextLogger listener = new GracefulShutdownContextLogger(env);

    GenericApplicationContext parent = new GenericApplicationContext();
    parent.refresh();
    GenericApplicationContext child = new GenericApplicationContext(parent);
    child.refresh();

    listener.onApplicationEvent(new ContextClosedEvent(child));

    assertThat(output.getAll()).doesNotContain("Graceful shutdown");

    child.close();
    parent.close();
  }

  @Test
  void shouldLogDrainCompleteOnStop(CapturedOutput output) {
    Environment env = mock(Environment.class);
    when(env.getProperty("spring.application.name", "unknown"))
        .thenReturn("test-service");

    GracefulShutdownContextLogger listener = new GracefulShutdownContextLogger(env);
    listener.start();
    assertThat(listener.isRunning()).isTrue();

    listener.stop();

    assertThat(listener.isRunning()).isFalse();
    assertThat(output.getAll()).contains("drain phase complete");
    assertThat(output.getAll()).contains("test-service");
  }

  @Test
  void shouldHaveMinIntegerPhase() {
    Environment env = mock(Environment.class);
    GracefulShutdownContextLogger listener = new GracefulShutdownContextLogger(env);
    assertThat(listener.getPhase()).isEqualTo(Integer.MIN_VALUE);
  }
}
```

### 4g — PubSubInflightTracker  *(only if PubSub detected and tracker missing)*

Create in the same module as the messaging helper, under the same package as the PubSub consumer config (e.g. `…streaming.pubsub`).

**Design notes:**
- Phase is `Integer.MAX_VALUE / 2 - 1` — one below `PubSubInboundChannelAdapter` (which uses `Integer.MAX_VALUE / 2`). This guarantees shutdown order: adapters stop pulling first (no new messages), then this bean waits for in-flight processing to drain.
- Timeout is read from `${graceful.shutdown.timeout-seconds:30}` — the same property used for HTTP and Kafka drain, so a single config key controls all drain windows.
- `@ConditionalOnProperty` guard must match the one used by the PubSub adapter beans (detected in Phase 1g).

```java
package <same package as PubSub consumer config>;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;

/**
 * Tracks in-flight PubSub messages during graceful shutdown.
 *
 * Phase is one below PubSubInboundChannelAdapter (Integer.MAX_VALUE / 2) so the adapters
 * stop pulling new messages first, then this bean waits for in-flight processing to drain.
 */
@Component
@Slf4j
@ConditionalOnProperty(value = "<PUBSUB_CONDITIONAL_PROPERTY>")
public class PubSubInflightTracker implements SmartLifecycle {

  private final AtomicInteger activeCount = new AtomicInteger(0);
  private volatile boolean running = false;

  @Value("${graceful.shutdown.timeout-seconds:30}")
  private int timeoutSeconds;

  public void increment() {
    activeCount.incrementAndGet();
  }

  public void decrement() {
    activeCount.decrementAndGet();
  }

  @Override
  public void start() {
    running = true;
  }

  @Override
  public void stop() {
    long deadline = Instant.now().toEpochMilli() + (long) timeoutSeconds * 1_000;
    log.info("PubSub drain: waiting for {} in-flight messages (timeout={}s)",
        activeCount.get(), timeoutSeconds);
    while (activeCount.get() > 0 && Instant.now().toEpochMilli() < deadline) {
      try {
        Thread.sleep(100);
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        break;
      }
    }
    int remaining = activeCount.get();
    if (remaining > 0) {
      log.warn("PubSub drain timeout: {} messages still in-flight, proceeding with shutdown",
          remaining);
    } else {
      log.info("PubSub drain complete: all in-flight messages finished");
    }
    running = false;
  }

  @Override
  public boolean isRunning() {
    return running;
  }

  @Override
  public int getPhase() {
    return Integer.MAX_VALUE / 2 - 1;
  }
}
```

**After creating the tracker, modify the messaging helper** (read the file first):

1. Add `PubSubInflightTracker` as a constructor-injected field (via `@RequiredArgsConstructor` or explicit constructor).
2. In every message handler lambda (both `manualAck` and `autoAck` paths):
   - Call `inflightTracker.increment()` **before** the `try` block.
   - Add a `finally` block at the end of the `try` containing `inflightTracker.decrement()`.

The `finally` placement is critical — it must cover all exit paths including any `return` statements inside `catch` blocks (Java guarantees `finally` runs even after `return`).

Before modifying the messaging helper, also find its test class:
```
grep pattern: <MessagingHelperClassName>Test
glob: **/src/test/**/*.java
output_mode: files_with_matches
```
Read the test class. Add `@Mock private PubSubInflightTracker inflightTracker;` so `@InjectMocks` can satisfy the new dependency. Mockito's default behavior for void methods (no setup needed) is correct for `increment()`/`decrement()`.

### 4h — PubSubInflightTrackerTest  *(only if PubSub detected and tracker missing)*

Create in `src/test/java/<same package as PubSubInflightTracker>`.

```java
package <same package as PubSubInflightTracker>;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(OutputCaptureExtension.class)
class PubSubInflightTrackerTest {

  private PubSubInflightTracker tracker;

  @BeforeEach
  void setUp() {
    tracker = new PubSubInflightTracker();
    ReflectionTestUtils.setField(tracker, "timeoutSeconds", 2);
  }

  @Test
  void start_setsRunningToTrue() {
    tracker.start();
    assertThat(tracker.isRunning()).isTrue();
  }

  @Test
  void stop_setsRunningToFalse() {
    tracker.start();
    tracker.stop();
    assertThat(tracker.isRunning()).isFalse();
  }

  @Test
  void stop_returnsImmediately_whenNoInflightMessages(CapturedOutput output) {
    tracker.start();
    long start = System.currentTimeMillis();
    tracker.stop();
    assertThat(System.currentTimeMillis() - start).isLessThan(500);
    assertThat(output.getAll()).contains("PubSub drain complete");
  }

  @Test
  void stop_waitsUntilInflightDrains(CapturedOutput output) {
    tracker.start();
    tracker.increment();
    tracker.increment();

    ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor();
    executor.schedule(() -> {
      tracker.decrement();
      tracker.decrement();
    }, 300, TimeUnit.MILLISECONDS);

    tracker.stop();

    assertThat(output.getAll()).contains("PubSub drain complete");
    executor.shutdown();
  }

  @Test
  void stop_logsWarning_whenTimeoutExceeded(CapturedOutput output) {
    tracker.start();
    tracker.increment();

    tracker.stop();

    assertThat(output.getAll()).contains("PubSub drain timeout");
    assertThat(output.getAll()).contains("1 messages still in-flight");
  }

  @Test
  void getPhase_isOneBelowPubSubAdapterPhase() {
    assertThat(tracker.getPhase()).isEqualTo(Integer.MAX_VALUE / 2 - 1);
  }

  @Test
  void increment_decrement_tracksCountCorrectly() {
    tracker.increment();
    tracker.increment();
    tracker.decrement();
    tracker.start();

    long start = System.currentTimeMillis();
    tracker.stop();
    assertThat(System.currentTimeMillis() - start).isGreaterThanOrEqualTo(2_000);
  }
}
```

**timeoutSeconds is set to 2** via `ReflectionTestUtils` so the timeout test completes in 2 seconds instead of 30.

---

## Phase 5 — Completion Summary

After all files are written, print:

```
[spring-graceful-shutdown] Done

FILES CREATED / MODIFIED
  + <path to GracefulShutdownProperties>           (or SKIPPED — already existed)
  + <path to GracefulShutdownContextLogger>        (or SKIPPED — already existed)
  ~ <path to application-dev.properties>
  ~ <path to properties module pom.xml>            (if spring-boot-starter-validation was missing)
  + <path to GracefulShutdownPropertiesBindingTest>
  + <path to GracefulShutdownContextLoggerTest>
  + <path to PubSubInflightTracker>                (if PubSub detected)
  ~ <path to messaging helper>                     (if PubSub detected)
  + <path to PubSubInflightTrackerTest>            (if PubSub detected)
  ~ <path to messaging helper test>               (if PubSub detected)

HOW IT WORKS
  server.shutdown=graceful       → Spring drains the web layer before JVM exit.
  spring.lifecycle.timeout-*    → Maximum drain window (default 30s).
  Redis (Lettuce)                → Handled implicitly — Spring shuts down the
                                   connection pool via Lifecycle during the drain phase.
  spring.kafka.listener.*       → (if Kafka) Gives listener containers time to
                                   finish the current record before stopping.
  PubSubInflightTracker          → (if PubSub) Counts in-flight messages.
                                   Phase = Integer.MAX_VALUE/2 - 1, so adapters
                                   stop pulling first, then this bean drains.
                                   Timeout shared with graceful.shutdown.timeout-seconds.

VERIFY
  mvn -pl <properties module> test -Dtest=GracefulShutdownPropertiesBindingTest
  mvn -pl <configuration module> test -Dtest=GracefulShutdownContextLoggerTest
  mvn -pl <pubsub module> test -Dtest=PubSubInflightTrackerTest    (if PubSub detected)

ROLLBACK (if you want to undo)
  1. Delete GracefulShutdownProperties.java        (if newly created)
  2. Delete GracefulShutdownContextLogger.java     (if newly created)
  3. Remove the "# Graceful shutdown" block from application-dev.properties
  4. Remove spring-boot-starter-validation from the properties module pom.xml  (if added)
  5. Delete PubSubInflightTracker.java             (if created)
  6. Revert the messaging helper to its pre-change state via git

NEXT STEPS (manual — not automated)
  1. Set server.shutdown and spring.lifecycle.timeout-per-shutdown-phase in
     Consul/production config (these application-dev.properties values are dev-only).
  2. Tune graceful.shutdown.timeout-seconds to match your longest expected
     request/message processing time.
  3. Review spring.kafka.listener.concurrency against your partition count —
     each concurrent listener needs its own drain window slot.
  4. (if PubSub) Ensure terminationGracePeriodSeconds in the Kubernetes deployment
     is >= graceful.shutdown.timeout-seconds + ~5s startup buffer (recommended: >= 35s).
```
