# STRIDE Threat Model Assessment: Shopping Assistant Agent

This assessment analyzes the codebase, architecture, and threat boundaries of the **shopping-assistant** agent project against the six STRIDE pillars.

---

## 1. System Architecture & Boundaries

### Entry Points
- **HTTP / REST API Endpoints (FastAPI)**: Defined in `fast_api_app.py`, created via ADK `get_fast_api_app` with `web=True`. This generates endpoints for receiving user chats and interacting with the root agent.
- **Feedback POST Endpoint (`/feedback`)**: Exposes a public REST interface to submit conversation feedback.
- **LLM Prompt Input**: User queries processed directly by the Gemini LLM.

### Workflows / Logic
- **Root Agent (`root_agent`)**: Orchestrates the system's responses using the Gemini model client. It is configured with instructions to assist in shopping and discount redemption, ensuring standard retail safety.
- **Discount Redemption Tool (`redeem_discount_code`)**: Executes Python code checking a local Python dict to see if a coupon is valid, already redeemed, or missing a user ID.

### Data Storage & Infrastructure Layers
- **In-Memory Cache (`DISCOUNT_CODES`)**: In-memory dictionary tracking coupon redemption state. State resets when the server restarts (non-persistent).
- **Google Cloud Storage (GCS) Telemetry Bucket**: Receives uploaded OpenTelemetry logs.
- **Google Cloud Logging**: Receives structured application logging data.
- **Google Vertex AI / Gemini API**: Processes prompt requests.

---

## 2. STRIDE Evaluation

### 2.1 Spoofing
- **Threat**: A client could pass arbitrary `user_id` values when invoking discount redemption or sending feedback. Because there is no cryptographic authentication or session verification tying a `user_id` to a verified identity, any caller can spoof another user's identity.
- **Impact**: One user can redeem single-use coupons on behalf of another user, block another user from redeeming their coupon (denial of service/tampering), or spoof telemetry/feedback.
- **Mitigation/Recommendation**: Integrate proper session-based authentication (e.g. JWT tokens or verified API session headers) and ensure `user_id` is extracted from the authenticated context instead of accepting arbitrary values from input parameters.

### 2.2 Tampering
- **Threat 1: Race Conditions in State Changes**: The in-memory global state `DISCOUNT_CODES` is modified by `redeem_discount_code` concurrently when FastAPI handles requests on multiple threads. Without synchronization primitives (e.g., threading locks/async locks), race conditions could allow concurrent requests to redeem the same single-use discount code multiple times.
- **Threat 2: LLM Tool Parameter Manipulation**: A user can perform prompt injection attacks to force the LLM to invoke the `redeem_discount_code` tool with malicious parameters or bypass constraints. Although `redeem_discount_code` validates that `user_id` is not empty and the coupon exists, it cannot verify the legitimacy of the request.
- **Threat 3: Hardcoded API Credentials**: `CustomGemini` uses a hardcoded API key (`api_key="AIzaSyD-mock-key-value-12345"`). While it is a mock value, if replaced with a production key, anyone with codebase access can tamper with the resource.
- **Impact**: Double-redemption of single-use coupons, unauthorized access to resources, credential leaks.
- **Mitigation/Recommendation**:
  - Implement concurrent transaction locking or use a transactional database (e.g., Redis, Cloud Spanner) for stateful coupon redemptions.
  - Load Gemini API keys exclusively from secure environment variables or secret management services (e.g., Secret Manager) instead of hardcoding.

### 2.3 Repudiation
- **Threat**: The `redeem_discount_code` tool performs critical state transitions (marking coupons as redeemed) but does not write any persistent audit log (e.g., logger call) recording who triggered the redemption, the timestamp, or the session context.
- **Impact**: If a high-value discount is claimed fraudulently, the system has no persistent records (beyond transient stdout or metadata logs) proving who redeemed it or when.
- **Mitigation/Recommendation**: Emit secure, structured, write-once audit logs (using Google Cloud Logging or similar) immediately upon successful redemption containing transaction details, timestamp, and authenticated actor metadata.

### 2.4 Information Disclosure
- **Threat 1: Hardcoded Secrets**: Hardcoded mock API key in `agent.py` presents a risk if replaced with active credentials.
- **Threat 2: Telemetry Data Leakage**: The OpenTelemetry logging setup is configured to capture messages using `NO_CONTENT` format if `LOGS_BUCKET_NAME` is set. However, if this bucket is misconfigured or if `capture_content` is overridden, raw prompt/response logs containing PII (names, user IDs, payment/address info typed by customer) could be leaked to GCS.
- **Threat 3: Stack Trace / Internal Detail Leakage**: Unhandled exceptions in the FastAPI application could reveal internal directory layouts, code structures, or package versions to clients.
- **Impact**: Leakage of client PII, cloud credentials, or sensitive code logic.
- **Mitigation/Recommendation**:
  - Use secret scanners (like Semgrep or GitLeaks) in CI/CD to prevent secrets committing.
  - Implement custom FastAPI exception handlers to capture stack traces internally while returning sanitized, generic error responses to callers.

### 2.5 Denial of Service (DoS)
- **Threat 1: Rate Limiting Absence**: The FastAPI app lacks any rate-limiting controls. A malicious client could send millions of chat requests, consuming massive LLM API quotas, exhausting Gemini API limits, and incurring huge financial costs.
- **Threat 2: Memory Exhaustion**: Since `DISCOUNT_CODES` and session data are stored in-memory, a large volume of concurrent users could cause the memory consumption of the FastAPI container to grow, eventually crashing the container (OOM).
- **Impact**: Excessive API billing, application downtime.
- **Mitigation/Recommendation**:
  - Install a rate-limiting middleware (e.g., `slowapi` or API Gateway limits) to throttle incoming client requests.
  - Transition state management and session tracking to a scalable external cache/database.

### 2.6 Elevation of Privilege
- **Threat**: The FastAPI API endpoints are exposed to the public internet without authentication middleware (e.g., OAuth, API key validations). This allows any unauthenticated user to directly invoke the agent loop, execute prompt injections, and potentially call the discount redemption tool or any future tools.
- **Impact**: Unauthenticated callers can execute privileged backend tools.
- **Mitigation/Recommendation**: Implement standard API authentication (e.g., API Gateway, Firebase Auth, JWT validation) to guard all routes, ensuring only authorized clients can send requests.
