# Milestone FE-069 — safe public catalog retry

- Catalog GET requests now retry at most once after a transient 502/503/504 or network failure.
- Retry uses a bounded 120/240 ms delay and the original AbortSignal; navigation/unmount cancels both request and delay.
- Non-transient responses and all state-changing operations are not retried.

Verification:

- Storefront typecheck passed.
