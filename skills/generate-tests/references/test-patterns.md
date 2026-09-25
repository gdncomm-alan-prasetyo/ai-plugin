# Generate Tests — Code Patterns

Read at implementation time (after plan approved). Templates for integration tests, unit tests, Kafka, WireMock, JSON fixtures.

## Table of Contents

- [Integration Test Patterns](#integration-test-patterns)
- [Kafka Event Assertions](#kafka-event-assertions)
- [WireMock Stubs](#wiremock-stubs)
- [Response JSON Fixtures](#response-json-fixtures)
- [Unit Test Patterns](#unit-test-patterns)
- [Assertion Minimum](#assertion-minimum)

---

## Integration Test Patterns

### Class declaration

```java
@Controller(value = "my-controller",
    description = "Integration test for my controller",
    failOnUnmatchedStub = true)
public class MyControllerIntegrationTest extends BaseIntegrationTest {
```

- `@Controller` — project's custom annotation (not Spring's), from test helper package.
- `failOnUnmatchedStub = true` — WireMock fails loudly on unexpected HTTP calls.
- Always extends `BaseIntegrationTest`. Never duplicate lifecycle logic.
- `IntegrationRunner` (JUnit 5 extension) auto-loads MongoDB fixtures from `setup/{TestClass}/{testMethod}/entity/*.json` and WireMock stubs from `setup/{TestClass}/{testMethod}/api-mock/*.json` before each test.

### Constants

```java
// Test data identifiers — unique per class, unique per method for IDs used in async Kafka events
private static final String ORDER_ID = "order-test-001";
private static final String MEMBER_ID = "member-test-001";
private static final String PARTNER_CODE = "PARTNER_CODE";
private static final String JSON_DIR = "my-controller/";

// API paths — always compose from path constants, never hardcode strings
private static final String CREATE_PATH = ApiPath.BASE + ApiPath.MY_RESOURCE;
```

**ID uniqueness:** IDs appearing in async Kafka events must be unique per test method. Use method-specific suffixes (e.g. `"order-create-001"`, `"order-update-001"`) to prevent cross-test contamination.

### Repositories and Kafka

```java
@Autowired private MyEntityRepository myEntityRepository;
@Autowired private MemberCardRepository memberCardRepository;

// Only if Kafka event assertions are needed:
@Autowired private KafkaPublishTopicProperties kafkaPublishTopicProperties;
```

Inject repositories for direct DB setup and assertion. Avoid injecting service beans.

### BeforeEach

Seed master/reference data and build shared request objects:

```java
@BeforeEach
public void setUp() {
    this.myRequest = new MyRequest();
    this.myRequest.setField("value");
    // master data shared across all tests in this class
    this.masterPartnerRepository.save(buildPartner(PARTNER_CODE));
}
```

Seed transactional/per-test data inside each test method, not in `@BeforeEach`.

### Positive test — full flow

```java
@Positive
@Test
public void createResource_validRequest_success() throws Exception {
    // 1. Seed prerequisites
    this.memberCardRepository.save(buildMemberCard(MEMBER_ID));

    // 2. WireMock stubs for outbound HTTP calls
    StubApiHelper.createStub(StubApiHelper.StubOptions.builder()
        .httpMethod(HttpMethod.POST)
        .url("/external/api/find-member")
        .response(buildMemberResponse())
        .responseStatus(HttpStatus.OK)
        .build());

    // 3. Load expected response fixture
    MyResponse expected = this.jsonFileToObject(
        this.getJsonFilePathForResponse(JSON_DIR + this.getResponseFileName()),
        MyResponse.class);

    // 4. Perform HTTP call
    MvcResult result = this.mockMvc.perform(
            postJson(CREATE_PATH)
                .content(this.objectMapper.writeValueAsString(this.myRequest)))
        .andReturn();

    // 5. Assert HTTP response
    Response<MyResponse> actual = this.getContent(result,
        new TypeReference<Response<MyResponse>>() {});
    assertEquals(200, actual.getCode());
    assertThat(actual.getData()).isEqualToIgnoringGivenFields(expected,
        "id", "createdDate", "updatedDate", "createdBy", "updatedBy");

    // 6. Assert DB state
    MyEntity saved = this.myEntityRepository.findByOrderId(ORDER_ID);
    assertNotNull(saved);
    assertEquals(Status.ACTIVE, saved.getStatus());

    // 7. Assert Kafka event (if applicable — see Kafka section)
}
```

### Negative test — error flow

```java
@Negative
@Test
public void createResource_memberNotFound_failed() throws Exception {
    // Stub returns not-found response
    StubApiHelper.createStub(StubApiHelper.StubOptions.builder()
        .httpMethod(HttpMethod.POST)
        .url("/external/api/find-member")
        .response(buildEmptyResponse())
        .responseStatus(HttpStatus.OK)
        .build());

    MvcResult result = this.mockMvc.perform(
            postJson(CREATE_PATH)
                .content(this.objectMapper.writeValueAsString(this.myRequest)))
        .andReturn();

    Response<MyResponse> actual = this.getContent(result,
        new TypeReference<Response<MyResponse>>() {});
    assertEquals(418, actual.getCode()); // business error
    assertThat(actual.getErrors().get("request").get(0))
        .isEqualTo(ErrorCode.MEMBER_NOT_FOUND.getCode());

    // Assert NO side effects
    assertNull(this.myEntityRepository.findByOrderId(ORDER_ID));
}
```

Error code convention (project-standard):
- `200` — success
- `400` — request validation error
- `418` — business logic error (domain `ErrorCode`)
- `500` — unexpected system error

### Parameterized tests

Multiple input variants of same scenario:

```java
@Positive
@ParameterizedTest
@CsvSource({"VALUE_A, EXPECTED_A", "VALUE_B, EXPECTED_B"})
public void createResource_multipleValues_success(String input, String expected) throws Exception {
    // ...
}
```

### HTTP helpers

```java
postJson(PATH).content(json)        // POST — adds mandatory headers automatically
putJson(PATH).content(json)         // PUT
deleteJson(PATH)                    // DELETE
getJson(PATH)                       // GET
getJson(PATH).param("key", "value") // GET with query params
```

---

## Kafka Event Assertions

```java
// Never hardcode topic string — always use the topic properties bean
MyEvent event = await()
    .atMost(30, SECONDS)
    .until(
        () -> kafkaTestHelper.getMessageByTopic(
            kafkaPublishTopicProperties.getLoyaltyTransactionEvent(), // resolved with fork suffix
            MyEvent.class,
            e -> e.getOrderId() != null && e.getOrderId().equals(ORDER_ID)), // filter by unique ID
        Objects::nonNull);

assertNotNull(event);
assertEquals(expectedStatus, event.getStatus());
assertEquals(ORDER_ID, event.getOrderId());
```

Rules:
- Predicate must check **final state** (e.g. `status == COMPLETED`), not just `Objects::nonNull`.
- Always filter by a unique business ID to avoid picking up events from other concurrent tests.
- Never hardcode topic strings — topic properties bean appends fork suffix at runtime.
- Do not increase `atMost` timeout without log evidence; fix predicate or isolation first.

---

## WireMock Stubs

Two mechanisms exist — `BaseIntegrationTest.tearDownEach()` calls `WireMock.reset()` which clears both:

**Programmatic (preferred for one-off stubs):**
```java
StubApiHelper.createStub(StubApiHelper.StubOptions.builder()
    .httpMethod(HttpMethod.POST)
    .url("/external/api/path")
    .response(responseObject)
    .responseStatus(HttpStatus.OK)
    .build());
```

**JSON fixture (preferred for stubs reused across tests):**
Place JSON stub definitions in `src/test/resources/` and load via `WiremockApiHelper`, or use `IntegrationRunner`'s auto-load from `setup/{TestClass}/{testMethod}/api-mock/*.json`.

**JSON stub format:**
```json
{
  "url": "/external/api/path",
  "method": "POST",
  "status": 200,
  "response": { "data": "..." }
}
```

---

## Response JSON Fixtures

Place expected response JSON at:
```
src/test/resources/json/response/{directory}/{testMethodName}.json
```

`getResponseFileName()` auto-derives the filename from the calling method name. Always exclude volatile fields from fixture comparison:

```java
assertThat(actual.getData()).isEqualToIgnoringGivenFields(expected,
    "id", "createdDate", "updatedDate", "createdBy", "updatedBy");
```

---

## Unit Test Patterns

### Controller unit test (`*ControllerTest`)

Tests controller layer in isolation — mocks service, no Spring context.

```java
public class MyControllerTest {

  private static final String CHANNEL_ID = "web";
  private static final String REQUEST_ID  = "R001";
  private static final String CLIENT_ID   = "web";
  private static final String USERNAME    = "test";

  @InjectMocks
  private MyController myController;

  @Mock
  private MyService myService;

  private MockMvc mockMvc;
  private ObjectMapper mapper;

  @BeforeEach
  public void setUp() {
    initMocks(this);
    this.mockMvc = standaloneSetup(this.myController).build();
    this.mapper = new ObjectMapper();
    // build shared request objects
  }

  @AfterEach
  public void tearDown() {
    verifyNoMoreInteractions(this.myService);
  }

  @Test
  public void createResource_validRequest_success() throws Exception {
    when(this.myService.create(any())).thenReturn(buildEntity());

    this.mockMvc.perform(post(ApiPath.MY_RESOURCE)
            .accept(MediaType.APPLICATION_JSON_VALUE)
            .contentType(MediaType.APPLICATION_JSON_VALUE)
            .header("channelId", CHANNEL_ID)
            .header("requestId", REQUEST_ID)
            .header("clientId", CLIENT_ID)
            .header("username", USERNAME)
            .content(this.mapper.writeValueAsString(this.myRequest)))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.code", equalTo(200)));

    verify(this.myService).create(any());
  }

  @Test
  public void createResource_entityNotFound_returns418() throws Exception {
    doThrow(new AppRuntimeException(ErrorCode.ENTITY_NOT_FOUND))
        .when(this.myService).create(any());

    this.mockMvc.perform(post(ApiPath.MY_RESOURCE)
            // ... headers ...
            .content(this.mapper.writeValueAsString(this.myRequest)))
        .andExpect(status().isIAmATeapot())
        .andExpect(jsonPath("$.code", equalTo(418)))
        .andExpect(jsonPath("$.errors.request[0]", equalTo(ErrorCode.ENTITY_NOT_FOUND.getCode())));

    verify(this.myService).create(any());
  }

  @Test
  public void createResource_unexpectedException_returns500() throws Exception {
    doThrow(RuntimeException.class).when(this.myService).create(any());

    this.mockMvc.perform(post(ApiPath.MY_RESOURCE)
            // ... headers ...
            .content(this.mapper.writeValueAsString(this.myRequest)))
        .andExpect(status().isInternalServerError())
        .andExpect(jsonPath("$.code", equalTo(500)));

    verify(this.myService).create(any());
  }
}
```

Each error code must have its own dedicated test method. Always call `verify(service).method(args)` after each test to confirm the service was invoked with correct arguments.

### ServiceImpl unit test (`*ServiceImplTest`)

Tests service logic in isolation — mocks dependencies, no Spring context.

```java
@ExtendWith(MockitoExtension.class)
public class MyServiceImplTest {

  @InjectMocks
  private MyServiceImpl myService;

  @Mock
  private MyRepository myRepository;

  @Mock
  private AnotherService anotherService;

  @AfterEach
  public void tearDown() {
    Mockito.verifyNoMoreInteractions(myRepository, anotherService);
  }

  @Test
  public void processOrder_validInput_success() {
    when(myRepository.findById(any())).thenReturn(Optional.of(buildEntity()));
    when(anotherService.calculate(any())).thenReturn(100);

    MyResult result = myService.processOrder(buildRequest());

    assertNotNull(result);
    assertEquals(100, result.getPoints());
    verify(myRepository).findById(any());
    verify(anotherService).calculate(any());
  }

  @Test
  public void processOrder_entityNotFound_throwsException() {
    when(myRepository.findById(any())).thenReturn(Optional.empty());

    try {
      myService.processOrder(buildRequest());
    } catch (AppRuntimeException ex) {
      assertEquals(ErrorCode.ENTITY_NOT_FOUND.getCode(), ex.getErrorCode());
      verify(myRepository).findById(any());
    }
  }
}
```

Alternatively use `assertThrows`:
```java
assertThrows(AppRuntimeException.class, () -> myService.processOrder(buildRequest()));
```

---

## Assertion Minimum

Every test method must contain at least one assertion below. Pick the most meaningful — do not pick a trivial one just to satisfy the rule:

| Layer | Minimum assertion |
|---|---|
| Integration — HTTP response | `assertEquals(200, actual.getCode())` or equivalent error code |
| Integration — DB state | `assertNotNull(repo.findByXxx(...))` or field-level `assertEquals` |
| Integration — Kafka event | `assertNotNull(event)` + at least one field assertion |
| Controller unit test | `andExpect(status().isOk())` + `andExpect(jsonPath("$.code", equalTo(200)))` |
| ServiceImpl unit test | `assertNotNull(result)` / `assertEquals(expected, actual)` / `assertThrows(...)` |

A `verify(service.method(...))` call alone is **not** an assertion — it confirms invocation, not correctness of output. Always pair it with a state or response assertion.
