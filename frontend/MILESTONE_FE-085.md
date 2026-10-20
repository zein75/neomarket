# Milestone FE-085 — auth preview honesty

- Removed the artificial auth submission delay from the preview form.
- Until the BFF auth contract exists, the form immediately returns a blocked message and never implies a request is in flight or succeeded.
- Password mismatch validation remains a local precondition before this blocked state.

Verification:

- Storefront typecheck passed.
