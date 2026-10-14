# NeoMarket production go-live checklist

- [ ] Commit SHA, image digests, migration heads and contract hashes recorded.
- [ ] Generate `scripts/release_manifest.ps1` output and attach it to the release evidence.
- [ ] Run `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`; attach the successful CI/local log.
- [ ] Production compose uses private backend networking, non-root images and one-shot migrations.
- [ ] Backup/PITR evidence and a recent clean-room restore report attached.
- [ ] B2B, B2C and Admin readiness checks pass; no database or Redis public ports are exposed.
- [ ] Security negative tests, inventory concurrency tests and event idempotency tests pass.
- [ ] Canary plan approved: 1% → 5% → 25% → 100%, with abort thresholds for 5xx, latency, queue lag and invariant violations.
- [ ] Rollback manifest and incident owner are assigned before traffic is enabled.

An unchecked backup, restore, security or data-integrity gate is a NO-GO.
