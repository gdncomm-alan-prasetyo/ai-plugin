# API Documentation — Lite Mode Section Templates

Read when building the document (after Phase 1 scan). Fill each section from scanned code. Use actual values, never the placeholder strings below.

## Table of Contents

1. [Title](#section-1--title)
2. [Endpoint](#section-2--endpoint)
3. [Backward Compatibility](#section-3--backward-compatibility)
4. [Request Headers](#section-4--request-headers)
5. [Request Parameters](#section-5--request-parameters)
6. [Request Body](#section-6--request-body)
7. [Response](#section-7--response)
8. [Error Responses](#section-8--error-responses)

---

## Section 1 — Title

```
# API Documentation: {Human-Readable API Name}

> **Mode**: Lite (Partner Integration Guide)
> **Last Updated**: YYYY-MM-DD
```

---

## Section 2 — Endpoint

```
## Endpoint

| Method | Full URI                          | Description               |
|--------|-----------------------------------|---------------------------|
| POST   | `/api/{version}/{resource}/{sub}` | One-line business summary |
```

---

## Section 3 — Backward Compatibility

```
## Backward Compatibility

| Version | Status        | Summary                                                                            |
|---------|---------------|------------------------------------------------------------------------------------|
| v2.1.0  | ✅ Compatible  | `partnerId` is optional; existing clients are unaffected                           |
| v1.3.1  | ⚠️ BREAKING   | `currency` renamed to `currencyCode`; clients sending `currency` will receive null |

**Latest compatible version**: v{X.Y.Z}
```

- **Compatible**: new optional fields only; nothing removed or renamed.
- **BREAKING**: required field added, field removed/renamed, type changed, error code changed.

Per BREAKING entry add migration note below table:
```
> **Migration v{X} → v{Y}**: Replace `currency` with `currencyCode` (ISO 4217) in all request payloads.
```

---

## Section 4 — Request Headers

```
## Request Headers

| Header              | Type   | Required | Example Value                          | Description              |
|---------------------|--------|----------|----------------------------------------|--------------------------|
| `Authorization`     | String | Yes      | `Bearer eyJhbGci...`                   | JWT identity token       |
| `X-Idempotency-Key` | String | No       | `550e8400-e29b-41d4-a716-446655440000` | Duplicate-prevention key |
| `Content-Type`      | String | Yes      | `application/json`                     | Request body format      |
```

> **Cond.** = Conditionally required. Explain condition in Description cell.

---

## Section 5 — Request Parameters

```
## Request Parameters

### Path Variables

| Parameter  | Type   | Required | Description         |
|------------|--------|----------|---------------------|
| `memberId` | String | Yes      | Member's loyalty ID |

### Query Parameters

| Parameter | Type    | Required | Default | Constraints | Description           |
|-----------|---------|----------|---------|-------------|-----------------------|
| `page`    | Integer | No       | 0       | Min: 0      | Result page (0-based) |
```

> POST/PUT with no query params: state "No query parameters."

---

## Section 6 — Request Body

### 6.1 Field Table

```
## Request Body

### Fields

| Field            | Type   | Required | Format / Constraints    | Description              | PII? |
|------------------|--------|----------|-------------------------|--------------------------|------|
| `memberId`    | String | Yes      | UUID v4, max 36 chars   | Member's loyalty account | No   |
| `idempotencyKey` | String | Yes      | UUID v4, max 36 chars   | Duplicate-prevention key | No   |
| `customerEmail`  | String | Cond.    | RFC 5321, max 255 chars | Customer's email address | Yes  |
| `amount`         | Long   | Yes      | Min: 1                  | Points to lock           | No   |
```

> PII fields must never be logged.

### 6.2 Request Body Example

```json
{
  "memberId": "550e8400-e29b-41d4-a716-446655440000",
  "idempotencyKey": "7f3b1c20-1234-4abc-9def-000000000001",
  "amount": 500,
  "currency": "THB"
}
```

---

## Section 7 — Response

### 7.1 Response Headers

```
## Response

### Response Headers

| Header                   | Example Value      | Description                          |
|--------------------------|--------------------|--------------------------------------|
| `Content-Type`           | `application/json` | Response body format                 |
| `X-Request-Id`           | `req-abc-123`      | Echoed request ID for tracing        |
| `X-Rate-Limit-Remaining` | `97`               | Remaining requests in current window |
| `Retry-After`            | `60`               | Seconds until rate limit resets      |
```

### 7.2 Response Body Fields

```
### Response Body

| Field    | Type    | Nullable | Description                       |
|----------|---------|----------|-----------------------------------|
| `code`   | Integer | No       | HTTP status code (mirrored)       |
| `status` | String  | No       | Status label (OK, BAD_REQUEST...) |
| `data`   | Object  | Yes      | Success payload; null on error    |
| `errors` | Object  | Yes      | Error details; null on success    |
```

### 7.3 Success Response Example

**HTTP 200 OK**

```json
{
  "code": 200,
  "status": "OK",
  "data": {
    "lockId": "LOCK-20260330-001",
    "expiredAt": "2026-04-01T00:00:00Z"
  },
  "errors": null
}
```

---

## Section 8 — Error Responses

Scan `@RestControllerAdvice` and error enums — document **all** error codes. Per status: one-line trigger + JSON matching actual project format. Use error format extracted in Phase 1 error-handler scan. Status string, field names, structure must match actual code — not template below.

#### HTTP 400 — `@Valid` fails on mandatory field

```json
{"code":400,"status":"BAD_REQUEST","data":null,"errors":{"request":["idempotencyKey must not be blank","amount must be greater than 0"]}}
```

#### HTTP 401 — JWT missing/expired/invalid signature

```json
{"code":401,"status":"UNAUTHORIZED","data":null,"errors":{"request":["Authentication token is missing or invalid"]}}
```

#### HTTP 403 — JWT valid but role/scope insufficient

```json
{"code":403,"status":"FORBIDDEN","data":null,"errors":{"request":["Insufficient permissions. Required role: ROLE_PARTNER"]}}
```

#### HTTP 404 — Member/resource not found

```json
{"code":404,"status":"NOT_FOUND","data":null,"errors":{"request":["MEMBER_NOT_FOUND"]}}
```

#### HTTP 409 — `idempotencyKey` exists with different payload

```json
{"code":409,"status":"CONFLICT","data":null,"errors":{"request":["DUPLICATE_IDEMPOTENCY_KEY"]}}
```

#### HTTP 418 — Business rule violated (list ALL error codes — no "etc.")

```json
{"code":418,"status":"I_AM_A_TEAPOT","data":null,"errors":{"request":["INSUFFICIENT_POINT_BALANCE"]}}
```

#### HTTP 429 — Rate limit exceeded

```json
{"code":429,"status":"TOO_MANY_REQUESTS","data":null,"errors":{"request":["Rate limit exceeded. Retry after 60 seconds."]}}
```

#### HTTP 500 — Unexpected system failure

```json
{"code":500,"status":"INTERNAL_SERVER_ERROR","data":null,"errors":{"request":["Unexpected error occurred: [Exception Message]"]}}
```
