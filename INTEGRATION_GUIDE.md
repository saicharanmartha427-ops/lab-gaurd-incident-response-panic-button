# LabGuard AWS Integration Guide

This document defines the intended real-service integration points. **They are documentation and placeholders, not active integrations.** The supplied dashboard does not contact AWS.

## Proposed architecture

```text
Physical red panic button
        |
        v
ESP32 firmware (debounce button; create event ID; device identity)
        |
        | MQTT over TLS with device certificate
        v
AWS IoT Core topic: college/lab01/emergency
        |
        v
AWS IoT Rule / controlled ingestion path
        |
        v
AWS Lambda (validate, deduplicate, authorize, create incident)
        |                    |                     |
        v                    v                     v
Amazon S3             Amazon SNS              CloudWatch
incident record       IT admin alert           logs/metrics/alarms

Dashboard browser
        |
        | HTTPS + Cognito-issued access token
        v
Amazon API Gateway
        |
        v
Lambda API handlers <----> S3 / DynamoDB (recommended for queryable index)
```

### Important architecture note

S3 is appropriate for durable incident snapshots/audit artifacts, but it is not a convenient database for filtering and updating a frequently queried incident list. For a production implementation, consider DynamoDB as the incident index/state store and S3 for immutable or archival JSON records. This optional addition is not required for the current static demo.

## Suggested event payload

```json
{
  "schemaVersion": "1.0",
  "eventId": "device-generated-unique-id",
  "deviceId": "ESP32-LAB01-001",
  "labId": "LAB01",
  "eventType": "PANIC_BUTTON_PRESSED",
  "occurredAt": "2026-10-09T06:15:00Z",
  "severity": "CRITICAL",
  "firmwareVersion": "1.0.0"
}
```

Treat device payloads as untrusted input. Validate schema, timestamp tolerance, event size, device identity, allowed event types, and replay/duplicate behavior server-side. The browser must not be the authority for incident creation.

## Suggested API contract

Configure a real API Gateway base URL only after the backend is deployed and protected. The Settings page currently stores a URL as configuration text and deliberately performs no fetch/network request.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/incidents` | List incidents with pagination and filters |
| `GET` | `/incidents/{incidentId}` | Retrieve a single incident |
| `POST` | `/incidents` | Create a manual incident after authorization and validation |
| `PATCH` | `/incidents/{incidentId}` | Update status or add response notes |
| `GET` | `/lab/status` | Return verified telemetry and its source/freshness |
| `GET` | `/notifications` | Return notification history/delivery state |
| `GET` | `/health` | Return backend health, not device health |

Suggested response envelope:

```json
{
  "data": [],
  "page": 1,
  "pageSize": 25,
  "source": "aws",
  "generatedAt": "2026-10-09T06:15:00Z"
}
```

Include explicit telemetry metadata such as `source`, `observedAt`, and `staleAfterSeconds`. If no trustworthy data exists, return `UNKNOWN`; do not silently display `Online`.

## Service-by-service integration points

### 1. AWS IoT Core and ESP32

- Use MQTT over TLS and per-device X.509 certificates.
- Attach least-privilege IoT policies limited to required client IDs and topics.
- Define an event topic, for example `college/lab01/emergency`, and a separate heartbeat topic if needed.
- Implement button debouncing and a unique event ID in firmware.
- Avoid embedding shared secrets in firmware. Have a provisioning and certificate-rotation plan.
- The physical panic button indicates a button press. It does **not** inherently detect computer failures or network outages.

### 2. AWS Lambda

- Validate device identity and payload schema.
- Make event handling idempotent using `eventId`.
- Apply server-side authorization to manual dashboard submissions and status changes.
- Generate canonical incident IDs and timestamps server-side.
- Write durable incident records and report workflow failures explicitly.
- Never trust client-supplied severity, role, incident status, or device ID without validation.

### 3. Amazon API Gateway

- Use HTTPS and a Cognito authorizer or another appropriate identity layer.
- Add CORS for only the deployed dashboard origin.
- Validate requests, limit payload sizes, apply throttling, and return consistent error responses.
- Use separate read/write permissions for Lab Assistant and IT Administrator roles.
- The dashboard Settings page does not activate a connection; a backend client and auth flow must be implemented and tested before going live.

### 4. Amazon SNS

- Configure a topic and verify email/SMS subscriptions.
- Notify administrators only after the incident is validated and persisted.
- Track delivery failures and avoid exposing sensitive details in message bodies.
- Test with non-emergency demo events before enabling real alerts.

### 5. Amazon S3

- Block public access; use least-privilege bucket policies and encryption.
- Consider versioning, lifecycle/retention policies, and access logging.
- Never expose a bucket credential or privileged write operation to the browser.
- Store only necessary data and establish an approved retention policy.

### 6. Amazon CloudWatch

- Use structured JSON logs with correlation/event IDs.
- Create metrics and alarms for Lambda errors, failed notification deliveries, ingestion lag, and stale device heartbeat.
- Set log retention deliberately and avoid logging credentials or sensitive content.
- Browser logs in this demo are not CloudWatch logs.

### 7. Amazon Cognito

- Replace the demo role chooser with a real hosted UI or SDK-based sign-in.
- Enforce role claims at API Gateway/Lambda, not only in frontend navigation.
- Use short-lived tokens, secure session handling, and an account recovery policy.
- The current local demo role is cosmetic and provides no security.

## Frontend implementation notes

- `index.html`: page structure, navigation, forms, tables, dialogs, and integration status.
- `styles.css`: responsive visual system.
- `app.js`: local demo state, rendering, filtering, CSV/JSON export, and simulated workflow.
- `config.js` is intentionally not provided as an active backend configuration. The Settings form stores only a placeholder URL in local browser state and does not send requests.

When adding a real backend, isolate network calls in a small `api.js` module. Add explicit `DEMO`/`LIVE` environment selection, make demo mode the safe default, and show the backend-reported source and last update time. Do not fall back silently from a failed live request to sample data.

## Pre-deployment checklist

- [ ] AWS account and budget/alerts reviewed
- [ ] IoT certificates and per-device policies configured
- [ ] Device event schema and duplicate handling tested
- [ ] Lambda validation and least-privilege execution role configured
- [ ] API Gateway HTTPS routes and Cognito authorization tested
- [ ] CORS restricted to intended origin
- [ ] SNS subscriptions confirmed and delivery failure monitored
- [ ] S3 public access blocked, encryption and retention configured
- [ ] CloudWatch logs, metrics, alarms, and retention configured
- [ ] Network/computer health data source implemented independently
- [ ] Lab Assistant and IT Administrator permissions tested
- [ ] Incident workflow tested with a non-emergency test event
- [ ] Privacy, retention, and incident escalation approved by the institution
