# 09 — Резервирование данных, аварийное восстановление и RPO/RTO

## DR-001. Объекты данных и модель отказов

Back up B2B/B2C/Admin DB clusters, PG WAL/base backups, object storage with media artifacts, secrets/keys references, IaC and migration manifests, configuration snapshots excluding cleartext secrets. Redis ephemeral and не содержит source-of-truth. Угроза: процесс умер, primary lost, disk corrupted, operator drop/truncate, ransomware/компрометация, регион недоступен, recovery трех баз на разные моменты.

## DR-002. Политика и измеримые цели

- Target primary DB **RPO <=5 минут** при потере всего primary site, **RTO <=60 минут** для критичных write operations **только при инфраструктуре, способной это обеспечить**; process failover RTO <=5 мин. Эти цифры — требования к выбранному deployment, не обещание, что один VPS/реплика дают их.
- Для локальной транзакции с подтверждённым DB COMMIT должна выполняться DB durability на surviving storage/WAL; асинхронная offsite реплика может терять последние минуты при региональном отказе — **невозможно обещать нулевую потерю** без дополнительной синхронной репликации/цены доступности.
- Base backup >=daily, WAL continuously archived to encrypted offsite bucket, retention default 30 days PITR + monthly immutable copies 3–12 months (конкретный срок утвердить с legal/product), separate account/region, keys not stored in same storage bucket. Enforce retention lock/immutability where provider supports it.
- Backup verify <=24h (archive healthy, manifests/checksums); restore rehearsal monthly and after backup topology changes, quarterly full DR role-playing. Measured actual RPO/RTO, signed evidence and last successful timestamp visible on dashboard; missing recent backup blocks risky deploy.

## DR-003. Техника PITR

- Использовать managed PITR либо pgBackRest/Barman с basebackup+WAL; простой `pg_dump` не заменяет WAL PITR. `pg_dump` может быть дополнительным логическим экспортом, но не единственным способом достичь target RPO.
- Standby из реплики не заменяет независимую backup; logical replication или snapshot не заменяют immutable offsite copy.
- Validate WAL timeline continuity, latest archive timestamp, storage size/budget, corruption checks and restoring into isolated infrastructure. Restore drills не воздействуют на реальные prod secrets/endpoints.
- Включить alert при archive lag >2 мин (engineering threshold, tuning after validation), backup failure 1 cycle, old verified restore >30 дней, low disk and failed encryption key access.

## DR-004. Восстановление и cross-service reconciliation

1. Incident commander переводит write APIs к безопасному read-only/fail-closed режиму, фиксирует incident/timestamp и freeze on external side effects; отключает старые workers, сохраняет доступные логи/event IDs.
2. Выбрать recovery point/time and snapshot set. Три независимые базы могут восстановиться на несовпадающие LSN/time — считать их **временно несогласованными** до reconciliation.
3. Восстановить isolated/staging volumes под новыми credentials; проверить checksum/PG integrity/migration heads and configuration, применить **только совместимые** миграции.
4. Внутри B2B проверить stock vs reservation_lines, lifecycle statuses and ledger; B2C checkout/order vs B2B lifecycle, Admin ticket/decisions vs B2B product revisions, B2C catalog projection vs B2B; выявить missing or duplicate events.
5. Повторить outbox/inbox и safe idempotent request with exact IDs/versions; неизвестные эквайринг-платежи сверить с provider (if present) **до** любых возвратов/списаний. Невосстановимые/спорные случаи вывести на manual incident queue. Не создавать «компенсацию» с новым random order_id.
6. После подписанного release invariant report, role/access tests, probes, canary write разрешить обработку; далее постепенно расширять трафик и наблюдать.
7. Составить postmortem без blame с impact window, actual RPO/RTO, data corrections, action items.

## DR-005. Неприемлемые варианты

- Docker volume как единственная копия; `docker compose down -v` в окружении с реальными данными.
- Backup на том же единственном VPS без независимой копии; backup пароль рядом в репозитории; любой restore без тестирования.
- Утверждение «RPO=0» из наличия WAL без подтверждённой репликации/реального измерения.
- Возобновление при расхождениях после восстановления B2B и B2C из разных временных точек.

## DR-006. Приёмка

DR-T01: delete/wipe only **isolated staging** DB and restore from offsite PITR; DR-T02: recovery exact chosen time ±RPO; DR-T03: simulate loss latest WAL/backup and alert; DR-T04: restore one DB ahead/behind others and reconcile without duplicate stock; DR-T05: outage database + worker recovery no lost committed order; DR-T06: backup credentials compromised, revoke without losing ability to restore; DR-T07: verify encryption+retention+immutability; DR-T08: published RTO/RPO measured and signed. Failure to restore in target time => NO-GO.
