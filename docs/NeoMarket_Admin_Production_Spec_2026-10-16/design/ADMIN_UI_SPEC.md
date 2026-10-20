# NeoMarket Admin UI — точная реализация по Stitch с реальными данными

## 1. Источник визуальных требований

Оригиналы в архиве source: `docs/design-system/stitch/admin-panel/reference.png` и `docs/design-system/stitch/admin-panel/source-official.html` (а также актуальные токены/документация). Скриншот показывает технический neo-brutalist dashboard: верхняя панель, левый sidebar, компактные технические метки, KPI-виджеты, список заявок, панель карточки товара, чеклист и заметные решения. 2x PNG соответствуют CSS-viewport меньшей ширины — сравнивать после нормализации pixel ratio.

**Правило:** PNG + HTML — композиция и визуальная основа, но содержат демонстрационные данные. Точные токены принимаются из утверждённого Design System source. Отсутствующие токены — предмет ADR; нельзя изобретать новые цвета и считать их эталонными.

## 2. Глобальный layout

- `AdminShell`: фиксированное приложение с вертикальным navigation rail, header, contextual breadcrumbs, быстрым поиском и account menu. Mobile — drawer, responsive grid, sticky action bar только с видимыми статусами.
- Global providers: authenticated principal + permissions; theme tokens; i18n; server-state cache keyed by principal/scopes; no persistent token in localStorage.
- `DataGrid`: cursor pagination, сортировки на сервере, filter chips в URL, bulk selection snapshot (не «все текущие DOM строки»), skeleton, empty/error, keyboard+screenreader controls.
- `StatusBadge`: palette/state text and accessible non-color signal. Async `operation_status` отдельный от `business_status`.
- `RequestErrorPanel`: 401/403/409/412/422/429/502/503 и request_id; retry только безопасных операций; при 409 сохранение введённых комментариев.
- i18n `ru-RU` first; даты timezone из настройки пользователя с UTC при экспорте; цены с валютой, без float.

## 3. Страницы и компоненты

| Route | Компоненты / операции | Требуемое доказательство |
|---|---|---|
| `/dashboard` | `QueueMetricCard`, `SlaTrend`, `WorkloadByModerator`, `PendingOutboxAlerts`, `CategoryHealth`; drill-down | Метрики из реальных агрегаций, c `as_of`, без hardcoded KPI |
| `/moderation` | `TicketFilterBar`, `TicketQueue`, `SortSelector`, `ClaimIndicator`, `BulkAssign`; deep links | keyset курсор; фильтры; rights; нет потери/дублей |
| `/moderation/[id]` | `RevisionHeader`, `ProductDiff`, `MediaGallery`, `SkuTable`, `AttributeChecklist`, `SellerRiskPanel`, `ModerationDecisionPanel`, `DecisionTimeline`, `ClaimTimer` | В настоящем браузере проверить approve/reject/stale claim, 202→publication confirmed |
| `/products` | `ProductsGrid`, `PublicationStatus`, `VisibilityReasons`, `RevisionTimeline`, `OpenReports`, `UnpublishAction` | Только реальный каталог, права и reason-coded actions |
| `/taxonomy/categories` | `CategoryTree`, `CategorySearch`, `CategoryInspector`, `CategoryWizard`, `MovePreview`, `ImpactReview`, `VersionDiff` | add, edit, activate, archive, cycle prevention, impacted products |
| `/taxonomy/attributes` | `AttributeDefinitionTable`, `SchemaRuleEditor`, `InheritancePreview`, `ConstraintTester` | type validation + category rules in B2B |
| `/taxonomy/brands` | `BrandRegistry`, `AliasEditor`, `MergePreview`, `ReviewEvidence` | merge without lost references |
| `/reasons` | `ReasonList`, `PolicyVersion`, `ReasonForm`, `ReasonUsageView` | references remain immutable historical |
| `/sellers` | `SellerReviewQueue`, `SellerCasePage`, `SuspendWizard`, `RiskEvidence`, `SellerHistory` | suspend requires permission+reason and does not mutate orders blindly |
| `/reports` | `ReportsQueue`, `EvidenceViewer`, `PrivacyGuard`, `DecisionForm` | complainant privacy, evidence access checks |
| `/appeals` | `AppealDetail`, `IndependentReviewerBadge`, `OriginalDecision`, `NewOutcome` | actor separation, no rewrite of original decision |
| `/bulk-operations` | `DryRunSummary`, `ImpactReview`, `ApprovalChain`, `OperationProgress`, `ResultExport` | maker-checker, per-item receipts |
| `/audit` | `AuditSearch`, `AuditDetail`, `DiffViewer`, `VerifiedExport`, `AccessLog` | secure filtering/export, integrity validation |
| `/operations/events` | `OutboxPanel`, `DLQPanel`, `ReconciliationStatus`, `ReplayPreview` | no unauthorized/raw replay and visible lag |
| `/admin-users` | `StaffDirectory`, `RoleGrantEditor`, `SessionRevocation`, `MfaState`, `ApprovalPanel` | least privilege; separate approver |
| `/settings` | `QueuePolicy`, `WorkflowSettings`, `NotificationSettings`, `RetentionStatus` | versioned, audited settings change |

## 4. Moderation detail desktop structure

At canonical 1280 CSS px: sidebar ~200–240px according to HTML reference, top shell, 12-col layout. Queue (roughly 25–30% content), product inspection (remaining) with right-side sticky decision section where safe. **HTML/PNG supersede this descriptive approximation.** Header queue summary shows `waiting`, `in review`, `urgent`, `approved today` only if real metric exists. Product card contains title, public preview, seller info, category breadcrumb, SKU table, rich media, attribute quality hints, revision diff, policy checks, audit trail. Controls: claim, heartbeat indication, release, approve, request changes, reject, escalate and hard-block (permission-gated).

## 5. Taxonomy workspace

Tree supports drag-drop only as proposal, never browser-side authoritative reorder. Show breadcrumb and descendant count; create wizard Step A metadata, Step B attribute rules, Step C SEO/media, Step D impact+review, Step E publish. Side-by-side before/after with version and affected count. Prevent invalid parent choices in UI **and** B2B. Archived categories display immutable reference and redirects. Category schema simulator: sample product verifies field requirements before publishing changes.

## 6. UX flows and edge states

- Opening ticket already claimed: show current owner/expiry; disable protected actions; allow refresh or eligible escalated takeover, never silent override.
- Lost network after approve click: keep same idempotency key, use operation lookup; do not issue new approve with new key until original outcome resolved.
- Seller edits revision during review: show old/new diff, mark stale, invalidate decision form/claim; user must reopen latest ticket.
- Requested reason removed while editor open: 409/422, refresh dictionary retaining text.
- Category move affecting published products: server impact preview, destructive warning, typed confirmation and optional second reviewer.
- Published state pending due to outbox: show `Доставка решения выполняется`, retry status from server, no optimistic display of visibility.
- Missing media: neutral placeholder and issue flag; do not render sample merch as real product.
- Fail closed OIDC: inform staff, audit auth failure; no developer bypass in deployed environments.
- Tables 100k rows: no DOM-all pagination, server sorting; keyboard accessible virtualized rows if needed.
- Suspended seller: explicitly separate new listing ban vs fulfilment of open orders.

## 7. Accessibility and responsive

Target WCAG 2.2 AA; keyboard navigation, skip-to-content, complete accessible labels, error association, non-color statuses, focus management for sidepanels/dialogs, touch targets, reduced motion, no horizontal page overflow at 320px. High-density admin tables may have deliberate *inner table* horizontal scroll with visible column controls; not entire-page scrolling. Print/export modes redact restricted data.

## 8. Visual acceptance

1. Run canonical screenshot at original CSS viewport (derive from HTML) and DPR matching normalized reference; fixed fonts, animations disabled, deterministic timezone and fixtures; record `actual`, `expected`, `diff`.
2. Structural exactness: header, sidebar, top KPI, ticket list, detail view, decision panel, density, borders, colors, typography. Global pixel tolerance should be established from stable fonts/images, not arbitrarily raised until tests pass.
3. Real-data Playwright journey after structural fixture run: category create → seller create/submit → claim → review → approve → B2B ack → B2C public visibility; separate error journeys.
4. Review screenshots by human when no authoritative mobile/tablet originals exist; responsive baselines require explicit approval, not auto-generation.
5. Do not update official baselines without human-approved reason, corresponding diff and changelog.
