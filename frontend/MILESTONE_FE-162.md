# FE-162 — Live cart loading/error isolation

## Delivered

- Live storefront no longer renders preview cart items while the server snapshot is loading.
- Added explicit cart loading and recoverable error states with retry.
- On cart GET failure, local preview positions are cleared and the user sees a safe empty/error state rather than a misleading total.
- Preview mode keeps its local fixture behavior explicitly.

## Verification

- Storefront typecheck is the required check for this increment.
