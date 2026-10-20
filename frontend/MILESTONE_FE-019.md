# Milestone FE-019 / FE-040 / FE-048 shell alignment

- Seller and Admin shells now use the NeoMarket design-system tokens instead of inline Arial styling.
- Added responsive-ready private shell treatment, hard-edge shadow, 2px borders, Space Grotesk/Manrope/Space Mono and explicit access/status labels.
- Admin remains closed until OIDC + MFA is connected; seller data remains unavailable until owner-scoped BFF operations exist.

Verification: seller/admin TSX syntax check — PASS. Full framework build — NOT TESTED until pnpm/lockfile setup.
