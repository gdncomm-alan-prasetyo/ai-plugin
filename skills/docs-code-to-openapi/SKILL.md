---
name: docs-code-to-openapi
description: >
  Generates an OpenAPI 3.0 YAML spec from Java/Spring MVC REST controllers using pure
  static source analysis -- no running app, no Maven/Gradle build, no springdoc runtime
  required -- then mandatorily reconciles it against every other knowledge source the
  codebase holds (hand-written docs, real error-handling flow, interceptors, comments)
  before treating it as final. Use this whenever the user wants to document, generate a
  spec for, or produce "openapi yaml" / "swagger" / "swagger.yaml" for a Spring Boot REST
  API from its @RestController classes, or asks to "document this API" / "generate API
  docs" for a Java backend. Also trigger when the user names a specific controller file or
  a repo full of controllers and wants a spec bootstrapped from it. Works on a single
  controller file, a directory, or a whole multi-module repo.
argument-hint: "[path to controller file, directory, or repo]"
allowed-tools: ["Bash(python*)", "Read", "Glob", "Grep", "Write", "Edit"]
---

# Docs + Code to OpenAPI (static analysis, verified against everything else the repo knows)

Bootstraps an `openapi.yaml` from Java Spring MVC controllers by reading source text --
never by running the app or hitting a live `/v3/api-docs` endpoint. That's the point of
this skill: it works in repos that can't easily be built/run in the current environment
(missing DB, secrets, unfamiliar build tooling), at the cost of being a heuristic
approximation rather than a byte-for-byte accurate reflection of runtime behavior.

The mechanical bootstrap is only half the job. **A spec built solely from controller
annotations is never accurate on its own** -- error responses, global-interceptor
parameters, and business rules never show up on a `@RestController` method signature no
matter how good the parser is. So this skill treats "read every other knowledge source the
codebase holds and reconcile it into the spec" (step 3 below) as a **mandatory** phase, not
an optional deep-dive for when someone happens to want extra accuracy. Never hand back a
spec built from the script's output alone.

## Workflow

1. **Run the script** against the target path:

   ```bash
   python ${CLAUDE_PLUGIN_ROOT}/skills/docs-code-to-openapi/scripts/generate_openapi.py <path> \
     --output openapi.yaml --title "<API name>" --api-version 1.0.0
   ```

   `<path>` can be one controller file, a package directory, or an entire repo root
   (it walks the tree, skipping `target/`, `build/`, `node_modules/`, `.git/`). Point it
   at the repo root rather than just the controller package when you can -- constant
   classes and DTOs commonly live in sibling modules/packages, and the script needs to
   see them to resolve paths and build `components/schemas` instead of leaving `$ref`s
   dangling. **This produces a first draft only** -- do not stop here, and do not present
   this output to the user as a finished spec.

2. **Read every warning the script prints to stderr before touching the YAML.** These are
   not noise -- each one names something the static analysis could not confidently resolve
   (an ambiguous path constant, a `defaultValue` that's a constant reference rather than a
   literal, a field it couldn't parse, an unrecognized custom validator). Open the
   referenced file/line and resolve it by hand: that's almost always faster than trying to
   make the script smarter for a one-off case, and it's the reason the script reports
   these instead of silently guessing. Also spot-check the draft against the controller
   source directly -- `summary`/`description` inferred from a method name with no
   `@Operation` annotation, any `type: object, description: "Unresolved type '...'"`
   (a referenced class the script couldn't find), and `required: true` that came from a
   bean-validation annotation rather than Spring's own `@RequestParam` (see Heuristics
   below for why that's deliberate).

3. **Mandatory: check every other source of knowledge in the codebase before the spec can
   be considered final.** Do not skip this because the draft "looks complete" -- a
   controller method's signature structurally cannot reveal most of what's below, no matter
   how carefully it's parsed, so skipping this step guarantees a wrong-or-incomplete spec
   (especially error responses, which the script only ever emits a bare `200` for).

   **(a) Hand-written docs.** Look for a folder of hand-written API docs in the repo
   (`documentations/api-specs/`, `docs/api/`, a Postman collection, anything similarly
   resource-organized). These are a genuinely high-value knowledge source for exactly the
   things static analysis structurally cannot see: parameters injected by a global
   interceptor rather than declared per-method, the real error-response bodies users
   actually get, and external-system business rules (pagination quirks, backward-compat
   domain rules, IDP-specific translation tables) that live nowhere in the controller code
   at all. Fold this in, but treat it as *evidence to verify*, not ground truth to copy
   blindly -- docs drift out of sync with code. For every non-obvious claim (a param is
   optional, an endpoint exists, a default is applied), find the line of code that would
   prove or disprove it before writing it into the spec.

   **(b) The real request/error-handling flow.** A lot of a real API's behavior lives
   *between* controllers, in cross-cutting infrastructure no amount of smarter per-file
   parsing would ever see:
   - **A generic exception handler is not the only error path.** A `BusinessException`-style
     type caught in a base controller handles errors the *app* throws deliberately. Spring
     itself throws a separate family before a request ever reaches the controller method --
     malformed JSON, `@Valid` failures on nested body fields, missing `@RequestParam`s,
     method-level `@Validated` constraint violations -- and these are commonly caught by a
     *second*, independent `@ExceptionHandler`/`@ControllerAdvice` (sometimes confusingly
     named, e.g. `ErrorController` while actually being a `@ControllerAdvice`, not Spring
     Boot's `ErrorController` interface). Trace it to get the real error bodies, and check
     whether it reuses the exact `message=` text already sitting on your parsed DTOs'
     validation annotations (it very often does).
   - **Success status can be runtime-conditional, not just annotation-derived.** A shared
     response-building helper might take an explicit `HttpStatus` argument at some call
     sites and default at others (e.g. `genericHandling(HttpStatus.MULTI_STATUS, ...)` for
     a bulk endpoint that partially succeeds) -- grep the helper's call sites for an
     explicit status argument. Also check what it does with a `null`/empty result -- some
     codebases short-circuit that to a bare `204 No Content` with no envelope at all.
   - **Enumerate every interceptor/filter, not just the one docs happen to mention.** Grep
     for `implements HandlerInterceptor`, `implements Filter`, and `addInterceptors`/
     `WebMvcConfigurer` registrations. Check each one's `addPathPatterns`/
     `excludePathPatterns` scope precisely. Some short-circuit with their *own* hand-rolled
     response, bypassing the app's normal envelope entirely -- these can have subtly
     different shapes (e.g. missing a `data` key every other error response includes)
     worth calling out explicitly.
   - **Don't confuse inbound interceptors with outbound ones.** `ClientHttpRequestInterceptor`
     (or similarly-named client-side auth/logging classes) decorates *outgoing* calls this
     service makes to other systems -- irrelevant here, even though "Interceptor" appears
     in both names. Confirm which interface a class actually implements.
   - **Springdoc/swagger customizer beans are another invisible-to-source-scanning
     category.** An `OperationCustomizer` (or similar springdoc SPI) bean can inject
     parameters or alter documentation purely at spec-generation time, with no annotation
     on the controller at all. If the repo has springdoc as a dependency, grep for
     `OperationCustomizer`/`GlobalOpenApiCustomizer` beans specifically.
   - **A stale comment/Javadoc is itself a discrepancy worth reporting**, not just stale
     docs files -- e.g. a custom annotation's Javadoc claiming a `FooInterceptor` handles
     its default when no such class exists in the repo.

   **(c) Report, don't silently resolve, disagreements.** When hand-written docs, comments,
   and code disagree with each other, the code wins for what the spec should *say* -- but
   the disagreement itself is worth surfacing to the user, not quietly papered over. It
   usually means either a doc is stale or the code has a real bug, and either way that's
   the user's call, not yours.

4. **New to this pattern or want a concrete worked example first?** Read
   `references/example.md` -- it walks one realistic controller + DTO + constants-class
   through the whole pipeline by hand, side by side with what the script produces, so you
   can sanity-check your own target repo's output against something you already
   understand.

5. Save the final, human-reviewed spec wherever the user wants it (commonly
   `docs/openapi.yaml` or the repo root). If they also want human-readable Markdown or a
   hosted Swagger/Redoc page generated *from* this spec, that's a separate, standard step
   (e.g. `redocly build-docs`, `widdershins`) -- this skill's job ends at producing a
   correct OpenAPI document.

## What it recognizes

- **Test sources are excluded by default.** Anything under a `test`-named source root
  (`src/test/java`, `src/integrationTest/java`, ...) or matching `*Test.java` /
  `*Tests.java` / `*IT.java` / `*ITCase.java` is skipped entirely -- mock/fixture
  controllers used only to exercise test infrastructure (a common pattern: a minimal
  `@RestController` in `src/test` that exists purely to drive a base controller's error
  handling in an integration test) are not part of the real API surface and shouldn't be
  documented as if they were. Pass `--include-tests` to opt back in if you genuinely need
  to document one of these.
- Controllers: any class annotated `@RestController` or `@Controller`, regardless of
  filename.
- HTTP mappings: `@GetMapping` / `@PostMapping` / `@PutMapping` / `@PatchMapping` /
  `@DeleteMapping`, plus a class-level `@RequestMapping` prefix.
- Path values that are string literals, bare constant references, or `+`-concatenated
  chains of both (`ROOT + "/role" + SEARCH`) -- resolved by reading the constants class(es)
  in the same scan and doing fixed-point substitution, so declaration order and multi-hop
  chains both work.
- Parameters: `@RequestParam`, `@RequestHeader`, `@PathVariable`, `@RequestBody`,
  `@RequestPart`.
- `jakarta.validation` / `javax.validation` constraints: `@NotNull`, `@NotBlank`,
  `@NotEmpty`, `@Min`, `@Max`, `@Size`, `@Pattern`, `@Email`, `@Positive(OrZero)`,
  `@Negative(OrZero)` -- mapped to the matching OpenAPI keyword. Anything else (custom
  validators like `@NotEmptyList`) is treated as `required`-only, with a warning, since its
  actual semantics can't be inferred from the annotation name alone.
- DTOs: plain fields or Lombok-style (`@Data`/`@Builder` with no explicit getters needed),
  including `List<T>` / `Set<T>` / `Map<K,V>` and nested custom types, and enums (constants
  become the OpenAPI `enum` list).
- A generic response envelope (a class with exactly one type parameter, e.g.
  `CommonResponse<T>`) -- detected automatically and substituted per-operation so
  `ResponseEntity<CommonResponse<RoleResponse>>` produces one concrete schema with `data`
  correctly typed as `RoleResponse`, not a dangling `T`. The envelope is then **shaped to
  the specific response status** (see below) rather than emitted verbatim.
- The success status itself, where it isn't 200: an explicit `@ResponseStatus`, or an
  `HttpStatus.X` passed as the first argument to whatever helper the method delegates to
  (`genericHandling(HttpStatus.MULTI_STATUS, ...)`). The second is a heuristic and emits a
  warning to confirm, since an `HttpStatus` in a method body can just as easily be an
  error path.

## The envelope is per-status, not one shape for every response

An envelope class carries every field the app can *ever* return, so copying it verbatim
into each response documents a 200 as though it might also carry `messages` and some
arbitrary `code`. `shape_envelope()` pins it to the one status it belongs to:

- **`code`** -- `example` is that response's HTTP status code.
- **`status`** -- `example` is that status's `HttpStatus` reason phrase, spelled exactly as
  `getReasonPhrase()` returns it (`OK`, `Multi-Status`, `Internal Server Error`), because
  that is literally what the app writes into the field.
- **`messages`** -- dropped from every 2xx. It is populated only by the error handlers, so
  on a success response it is a field that can never appear.
- **`data`** -- dropped from every 4xx and 5xx, for the mirror-image reason: only the
  success path populates it.

The last two are the same rule seen from both ends. The envelope's success half and its
error half are mutually exclusive in practice, so documenting both on every response
describes a payload the app never sends.

Carry the rule through the reconciliation pass in step 3 when you hand-add 4xx/5xx
responses: those keep `messages`, drop `data`, and take their `code`/`status` from the
status they document. A shared error schema (`ErrorResponse`) satisfies this for free,
since every response using it is an error one -- define it without a `data` property.

**One thing to verify rather than assume:** dropping `data` describes the wire format only
if the serializer actually omits nulls. In Jackson that means `@JsonInclude(NON_NULL)` on
the envelope class or a global `spring.jackson.default-property-inclusion=non_null`. With
neither, the default is `ALWAYS` and the real response carries `"data": null` -- present,
not absent. Grep for both before relying on it, and say so in the reconciliation report if
the codebase has neither, since then the spec and the wire disagree by exactly this field.
- Existing `@Operation(summary=..., description=...)` / `@Tag` annotations -- used verbatim
  when present, since a human already wrote them.

## Heuristics worth knowing about

This is regex + bracket-depth scanning, not a real Java parser, so it's tuned for
idiomatic Spring MVC and will say so via warnings rather than fail silently when it hits
something it doesn't recognize. Specifically:

- **Functional vs. annotated "required".** If a param carries a bean-validation constraint
  (`@NotNull` etc.) the script marks it `required: true` even if Spring's own
  `@RequestParam(required=false)` says otherwise -- because the app will reject the request
  at validation time regardless of what Spring's binder allows through. This is the more
  useful read for an API consumer, but it is a judgment call, not a fact extracted from the
  code -- override it if a given case doesn't fit.
- **`defaultValue` that isn't a string literal** (e.g. `Strings.EMPTY`, a project-specific
  constant) can't be resolved to an actual value and is flagged as a warning instead of
  guessed. The extremely common `*.EMPTY` idiom (Apache Commons/log4j "empty string"
  constants) is special-cased to `""` since it's unambiguous.
- **Ambiguous constants.** If two different constants classes both declare a field with
  the same simple name and the referencing code uses the bare name, the script can't know
  which one you meant and flags it -- qualify the reference (`ClassName.FIELD`) in the
  source, or resolve manually.
- **Dynamic/reflection-based routing** (paths built at runtime, `RequestMappingHandlerMapping`
  manipulation, etc.) is out of scope entirely -- it isn't string-analyzable, and the script
  won't pretend otherwise.
- **Generic substitution only handles single-type-param classes** (`class Foo<T>`), applied
  recursively however deeply nested (`CommonResponse<SearchResponse<RoleResponse>>` resolves
  both levels, inlined rather than left as a dangling `$ref`, since the same wrapper could be
  instantiated with a different type elsewhere). A class declared `class Pair<K, V>` isn't
  recognized as generic at all -- its `K`/`V`-typed fields will come out unresolved.
- **One field-vs-method heuristic to know about:** fields are distinguished from methods by
  checking whether a `{` appears before the terminating `;` after `private ` -- a method
  body always has one, a field declaration never does. This is reliable for idiomatic code
  but would misfire on something unusual like a field initialized from an anonymous inner
  class literal spanning multiple statements; such cases are rare enough not to special-case.

## CLI reference

```
python generate_openapi.py <path> [--output openapi.yaml] [--title TITLE] \
    [--api-version VERSION] [--warnings-json warnings.json] [--include-tests]
```

`--warnings-json` dumps the same warnings shown on stderr as a JSON array, useful if you
want to grep/process them programmatically rather than reading the console output.
