# FE-158 — Authoritative cart removal

## Delivered

- Live storefront now loads the server cart snapshot on entry.
- Removing an item performs CSRF-protected `removeGuestCartItem` and applies the complete returned cart snapshot.
- Repeated mutations are disabled while pending; failures leave local cart state unchanged and expose a recoverable notice.
- Preview mode remains explicit and local-only instead of pretending to be a server mutation.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
