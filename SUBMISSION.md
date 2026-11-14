# Submission

> Replace everything in _italics_. Be concise: bullet points are fine. We read every word.

## Candidate
- **Name:** Muzahidin
- **Assignment chosen:** B (Workflow)
- **Time spent (honest estimate):** 9h

## How to run
```bash
# exact commands from a clean clone: setup, run, test
# Install dependencies
pip install -r requirements.txt

# Apply database migrations
python manage.py migrate

# Import tenants, campaigns, and leads
python manage.py import_fixtures

# Start the mock telephony provider (terminal 1)
python -m mock_telephony --failure-scale 0

# Start Django webhook server (terminal 2)
python manage.py runserver

# Start the campaign dispatcher (terminal 3)
python manage.py run_dispatcher

# Run tests
python manage.py test

# Export final lead states
python manage.py export_final_state
```

## Design
## Design

I implemented a database-backed state machine using Django ORM. The database maintains persistent records for tenants, campaigns, leads, call attempts, active call reservations, DND phone numbers, and webhook events.

The dispatcher selects eligible leads based on campaign calling windows, retry schedules, callback priority, tenant concurrency limits, and phone-level reservations. Each call attempt is persisted with a unique request ID before contacting the telephony provider. Webhook events are verified using HMAC-SHA256, stored in the database, and processed idempotently.

### Lead State Machine

```text
             PENDING
                |
                v
          Prepare Attempt
                |
                v
         Submit to Provider
                |
       +--------+--------+
       |        |        |
       v        v        v
   ACCEPTED  REJECTED  UNKNOWN
       |        |        |
       |        |        v
       |        |   Reconcile with
       |        |      Provider
       |        |        |
       +--------+--------+
                |
                v
           Call Outcome
                |
       +--------+---------+
       |        |         |
       v        v         v
   Terminal   Retry    Callback
       |        |         |
       v        +----+----+
   COMPLETED         |
                     v
                  PENDING

     Attempts exhausted -> EXHAUSTED
     Global DND         -> DND_BLOCKED
```

### At-Most-Once Dialling

- Every call attempt receives a persistent request ID before submission.
- Database transactions and row-level locking protect critical state transitions.
- Active call reservations prevent simultaneous calls to the same phone number and enforce concurrency limits.
- After an ambiguous timeout or restart, the existing request ID is reconciled with the provider before any further submission.
- Prepared and unknown attempts are reused rather than creating new attempts unnecessarily.

## Decisions & assumptions
## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| Used a database-backed state machine instead of Temporal | Simpler to implement and maintain using Django ORM and persistent database records | Temporal workflows |
| Reused the same request ID for ambiguous submissions | Prevents creating a new call when the provider may already have accepted the previous request | Generating a new request ID after a timeout |
| Stored webhook events before processing | Allows recovery from duplicate deliveries and interrupted processing | Processing webhooks directly without persistence |
| Used separate active call reservation records | Provides explicit tracking of active phone reservations and tenant concurrency | In-memory locks |
| Used database transactions and row-level locking | Protects critical state transitions from concurrent updates | Unprotected database updates |
| Used provider reconciliation for unknown and active attempts | Recovers call outcomes when responses or webhooks are missing | Relying only on webhook delivery |
| Used a polling-based dispatcher | Keeps the workflow simple and allows periodic reconciliation and dispatch | Event-driven background task queue |

## Failure modes considered
## Failure modes considered

| Failure mode | How the solution handles it |
|---|---|
| Invalid fixture JSON or missing fixture files | The import command validates required configuration and checks that fixture files exist before importing. |
| Re-running fixture import | Uses `update_or_create()` to avoid creating duplicate tenants, campaigns, and leads. |
| HTTP 503 response | Marks the submission as rejected; it does not count towards accepted attempts. |
| HTTP 504 timeout | Marks the attempt as unknown and reconciles it with the provider using the existing request ID. |
| Duplicate webhooks | Uses persistent webhook events and idempotent processing to avoid applying the same event repeatedly. |
| Invalid webhook signature | Verifies HMAC-SHA256 signatures and rejects invalid requests. |
| Lost or delayed webhooks | Reconciles active and unknown attempts with the provider to recover call outcomes. |
| Dispatcher process restart | Recovers prepared, unknown, and active attempts from persistent database records. |
| Concurrent dispatch attempts | Uses database transactions, row-level locking, and active call reservations to protect concurrency and phone-level exclusivity. |
| Global DND | Stores DND phone numbers globally and blocks other eligible leads with the same phone number. |

### Known limitations

- Recovery depends on the database and telephony provider being available.
- The dispatcher uses polling rather than an event-driven job queue.
- The implementation has not been extensively load-tested with multiple dispatcher workers at production scale.

## Testing
The Django test suite covers the following areas:

Scheduling: Campaign calling windows, eligible calling times, retry delays, callback scheduling, and priority ordering.

Call attempts: Attempt numbering, reuse of prepared and unknown attempts, and accepted-attempt counting.

Provider responses: Handling of HTTP 422, 503, and ambiguous 504 responses.

Webhook processing: Signature verification, duplicate event handling, and idempotent processing.

Failure recovery: Reconciliation of unknown attempts, recovery from lost webhooks, and resubmission when the provider confirms that a request was not placed.

Concurrency: Tenant-wide concurrency limits and global phone-number reservations.

Lead outcomes: Retry handling, callbacks, DND blocking, and attempt exhaustion.

The complete Django test suite was executed successfully.

Not tested

Large-scale load testing with thousands of concurrent calls.

Extensive multi-worker stress testing.

Every possible provider failure combination across different random seeds.

These were not included due to the assignment's time constraints; priority was given to the core business rules, failure handling, and recovery scenarios.

## Results
Dispatcher execution: Completed a full campaign run using the mock telephony provider.

Final output: Generated final_state.csv with the required columns and ordering.

Provider validation: Checked the provider's /admin/report and /admin/leads endpoints.

Violation count: [Insert actual value from /admin/report]

CSV comparison: [Insert whether final_state.csv matches /admin/leads]

Crash recovery: [Insert result of the kill -9 and restart test, if performed]

## If I had another day
Improve crash-recovery testing: Perform repeated kill -9 and restart tests at different stages of call submission and webhook processing.

Expand failure-injection testing: Test additional combinations of provider timeouts, rejected requests, duplicate webhooks, and delayed webhook delivery.

Improve observability: Add structured logging, per-campaign progress tracking, and metrics for retries, callbacks, and reconciliation.

Test concurrent workers: Validate that multiple dispatcher processes can operate safely without exceeding tenant concurrency limits or creating duplicate calls.

Improve scalability: Evaluate database indexing, query optimization, and batching for larger campaigns and higher call volumes.

Strengthen operational reliability: Add monitoring and clearer error handling for prolonged database or provider outages.
