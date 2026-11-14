# AI Usage Disclosure

AI tools are allowed. We want to know **how** you used them, because using them well is a
skill. Honest answers are never held against you. Discovering undisclosed use is.

## Tools used
ChatGPT (OpenAI).

## What I used them for
Understanding the assignment requirements and breaking them into implementation tasks.

Discussing Django project architecture, database models, and state management.

Getting guidance on scheduling, retry handling, webhook processing, concurrency, and crash recovery.

Debugging implementation issues and reviewing management commands.

Developing and reviewing test cases for scheduling, callbacks, retries, DND, concurrency, and reconciliation.

Reviewing documentation and setup instructions.

## What I wrote or decided myself
Reviewed the assignment requirements and made implementation decisions based on them.

Worked through the database models, application structure, and integration of the different components.

Evaluated suggested solutions and made changes while implementing and testing the application.

Ran the application checks and tests locally.

## Where the AI was wrong or unhelpful
Some initial guidance did not cover recovery of accepted calls when webhooks never arrive. I identified this gap during review and added reconciliation for accepted calls.

Some suggestions required further verification against the mock provider's documented API contract.
## How I verified AI-generated code
Ran Django system checks.

Ran database migrations and verified the PostgreSQL connection.

Executed the Django test suite.

Added a separate test for accepted-call reconciliation.

Verified that the management commands were registered.

Checked the project configuration and dependencies locally.
