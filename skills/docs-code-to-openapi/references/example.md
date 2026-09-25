# Worked example

A minimal but representative fixture covering every pattern the script is built to handle:
a path-constants class, a `@RestController` using them, a Lombok DTO with nested
validated collections, and a generic response envelope. Read this once to calibrate what
"good" output looks like before trusting the script's output on an unfamiliar repo.

## Source

`constant/WidgetPath.java`

```java
public class WidgetPath {
  public static final String ROOT = "/api";
  public static final String WIDGET = ROOT + "/widget";
  public static final String WIDGET_SEARCH = WIDGET + "/search";
  public static final String WIDGET_UPSERT = WIDGET + "/upsert";
  private WidgetPath() {}
}
```

`response/CommonResponse.java` (the generic envelope)

```java
@Data
@Builder
public class CommonResponse<T> {
  private int code;
  private String status;
  private List<String> messages;
  private T data;
}
```

`request/WidgetUpsertRequest.java`

```java
@Data
@Builder
public class WidgetUpsertRequest {
  @NotBlank(message = "Required String 'name' in body request must not be blank.")
  private String name;

  private List<@NotBlank(message = "Each String tagName must not be blank.") String> tagNames;
}
```

`response/WidgetResponse.java`

```java
@Data
@Builder
public class WidgetResponse {
  private String name;
  private List<String> tagNames;
}
```

`response/SearchResponse.java` (a second, independent generic wrapper -- note the
package-private fields with no `private` modifier, a common Lombok idiom the script
handles the same as explicit `private` fields)

```java
@Data
@Builder
public class SearchResponse<T> {
  List<T> result;
  PagingDetail paging;
}
```

`response/PagingDetail.java`

```java
@Data
@Builder
public class PagingDetail {
  private int pageNumber;
  private long totalRecords;
}
```

`controller/WidgetController.java`

```java
@RestController
@RequiredArgsConstructor
public class WidgetController extends BaseRestController {
  private final WidgetCrudService widgetCrudService;

  @GetMapping(path = WidgetPath.WIDGET_SEARCH)
  public ResponseEntity<CommonResponse<SearchResponse<WidgetResponse>>> searchWidgets(
      @RequestParam(required = false)
      @NotNull(message = "Required integer parameter 'page' is not present.")
      @Min(value = 1, message = "The 'page' parameter must be a positive integer.")
      Integer page,

      @RequestParam(defaultValue = Strings.EMPTY) String findValue
  ) {
    return genericErrorHandling("searchWidgets", ..., () -> ...);
  }

  @PostMapping(path = WidgetPath.WIDGET_UPSERT)
  public ResponseEntity<CommonResponse<WidgetResponse>> upsertWidget(
      @RequestBody @Valid WidgetUpsertRequest request) {
    return genericErrorHandling("upsertWidget", request, () -> ...);
  }
}
```

## Run

```bash
python scripts/generate_openapi.py path/to/fixture --output openapi.yaml --title "Widget API"
```

## Expected output shape

```yaml
paths:
  /api/widget/search:
    get:
      tags: [Widget]
      summary: Search Widgets          # inferred from method name -- no @Operation present
      operationId: searchWidgets
      parameters:
        - name: page
          in: query
          required: true               # @NotNull wins over Spring's required=false --
          schema:                      # see "functional vs. annotated required" in SKILL.md
            type: integer
            format: int32
            minimum: 1
        - name: findValue
          in: query
          required: false              # defaultValue with no explicit `required` -> optional
          schema:
            type: string                # no `default: ""` -- Strings.EMPTY resolves to
                                         # nothing worth stating rather than a literal token
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  code: {type: integer, format: int32}
                  status: {type: string}
                  messages: {type: array, items: {type: string}}
                  data:                                # CommonResponse<T> unwrapped with
                    type: object                        # T = SearchResponse<WidgetResponse> --
                    properties:                          # and THAT generic is, in turn, resolved
                      result:                            # too, recursively, all inlined rather
                        type: array                      # than left as dangling $refs
                        items:
                          $ref: '#/components/schemas/WidgetResponse'
                      paging:
                        $ref: '#/components/schemas/PagingDetail'
  /api/widget/upsert:
    post:
      tags: [Widget]
      summary: Upsert Widget
      operationId: upsertWidget
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/WidgetUpsertRequest'}
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  code: {type: integer, format: int32}
                  status: {type: string}
                  messages: {type: array, items: {type: string}}
                  data: {$ref: '#/components/schemas/WidgetResponse'}

components:
  schemas:
    WidgetUpsertRequest:
      type: object
      required: [name]
      properties:
        name: {type: string, minLength: 1}
        tagNames:
          type: array
          items: {type: string, minLength: 1}    # @NotBlank inside the generic's <>
                                                    # correctly attaches to the item schema
    WidgetResponse:
      type: object
      properties:
        name: {type: string}
        tagNames: {type: array, items: {type: string}}
```

Things to notice, in order of how often they trip people up on real repos:

1. **Neither generic envelope appears as its own top-level schema.** You will not find
   `CommonResponse` *or* `SearchResponse` in `components/schemas` -- any class with a
   single type parameter gets resolved inline, substituted with whatever it was actually
   instantiated with at that call site, however deeply nested (`CommonResponse<SearchResponse<WidgetResponse>>`
   resolves both levels). If you're looking for one of these wrapper classes by name and
   can't find it, that's correct, not a bug -- the same wrapper might be instantiated with
   a *different* type elsewhere in the same API, so it can't be one shared `$ref`.
2. **`required` on params can differ from the Spring annotation you're staring at.** `page`
   above has `@RequestParam(required = false)` in the source yet ends up `required: true`
   in the spec, because `@NotNull` means the app 400s without it anyway. This is the one
   heuristic worth re-reading in SKILL.md if the output looks "wrong" at a glance.
3. **Only single-type-param generics (`class Foo<T>`) are substituted this way.** A class
   declared like `class Pair<K, V>` isn't recognized as generic at all by the script (its
   fields typed `K`/`V` will show up as unresolved) -- multi-parameter generics are rare
   enough in typical request/response DTOs that this wasn't worth the added complexity for
   a v1 static-analysis tool; patch those by hand if you hit one.
