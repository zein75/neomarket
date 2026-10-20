'use client';

import { useEffect, useState } from 'react';

type DashboardMetrics = {
  as_of: string;
  provenance: Record<string, string>;
  workload_by_moderator: { staff_id: string; in_review: number }[];
  pending: number;
  in_review: number;
  overdue: number;
  complaints_pending: number;
  complaints_in_review: number;
  complaints_overdue: number;
  average_resolution_seconds: number | null;
  resolved_decision_count: number;
  oldest_pending_seconds: number | null;
  oldest_complaint_pending_seconds: number;
  outbox_pending: number | null;
  outbox_dead: number | null;
};

function metricError(body: unknown, status: number) {
  if (body && typeof body === 'object') {
    const value = body as { code?: unknown; message?: unknown; detail?: unknown };
    if (typeof value.code === 'string') return `${value.code} (${status})`;
    if (typeof value.message === 'string') return value.message;
    if (typeof value.detail === 'string') return value.detail;
  }
  return `Не удалось загрузить показатели (${status})`;
}
const number = new Intl.NumberFormat('ru-RU');
function duration(seconds: number | null) {
  if (seconds == null) return 'Нет данных';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${number.format(days)} д ${number.format(hours)} ч`;
  if (hours) return `${number.format(hours)} ч ${number.format(minutes)} мин`;
  return `${number.format(minutes)} мин`;
}
function dateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Время не распознано' : `${new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(date)} UTC`;
}

function MetricCard({ label, value, detail, href, tone = '' }: { label: string; value: string | number; detail: string; href?: string; tone?: string }) {
  const content = <><span className="metric-label">{label}</span><strong className="metric-value">{typeof value === 'number' ? number.format(value) : value}</strong><span className="metric-detail">{detail}</span></>;
  return href ? <a className={`metric-card ${tone}`} href={href}>{content}<span className="metric-link">Открыть список →</span></a> : <article className={`metric-card ${tone}`}>{content}</article>;
}

export function AdminDashboard() {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoading(true); setError('');
      try {
        const response = await fetch('/api/admin/v1/dashboard', { cache: 'no-store', headers: { Accept: 'application/json' } });
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(metricError(body, response.status));
        if (active) setMetrics(body as DashboardMetrics);
      } catch (caught) {
        if (active) { setMetrics(null); setError(caught instanceof Error ? caught.message : 'Не удалось загрузить показатели'); }
      } finally { if (active) setLoading(false); }
    };
    void load();
    return () => { active = false; };
  }, []);

  return <>
    <p className="eyebrow">ADMIN CONSOLE / OVERVIEW</p>
    <div className="admin-heading-row"><div><h1>Операционный обзор</h1><p className="admin-intro">Показатели рассчитаны Admin API. Время и источник данных отображаются вместе с агрегатами.</p></div><a className="admin-button admin-button-link" href="/moderation">Перейти к очереди</a></div>
    {loading && <div className="admin-empty" role="status">Загрузка показателей…</div>}
    {error && <div className="admin-alert" role="alert"><strong>Метрики недоступны</strong><span>{error}</span><p>Показатели не заменяются локальными числами. Проверьте Admin-сессию и разрешение dashboard.read.</p></div>}
    {metrics && <>
      <div className="dashboard-meta"><span>Срез данных</span><strong>{dateTime(metrics.as_of)}</strong><button className="text-button" onClick={() => window.location.reload()}>Обновить</button></div>
      <section className="dashboard-section" aria-labelledby="moderation-metrics"><div className="section-heading"><div><p className="eyebrow">WORK QUEUE</p><h2 id="moderation-metrics">Модерация</h2></div><a className="text-link" href="/moderation">Открыть очередь →</a></div><div className="metric-grid">
        <MetricCard label="Ожидают" value={metrics.pending} detail={`Самая старая заявка: ${duration(metrics.oldest_pending_seconds)}`} href="/moderation" />
        <MetricCard label="В работе" value={metrics.in_review} detail="Заявки со статусом IN_REVIEW" href="/moderation" />
        <MetricCard label="Просрочены" value={metrics.overdue} detail="По настроенному SLA модерации" href="/moderation" tone={metrics.overdue > 0 ? 'metric-alert' : ''} />
      </div></section>
      <section className="dashboard-section" aria-labelledby="complaint-metrics"><div className="section-heading"><div><p className="eyebrow">TRUST & SAFETY</p><h2 id="complaint-metrics">Жалобы</h2></div><a className="text-link" href="/reports">Открыть жалобы →</a></div><div className="metric-grid">
        <MetricCard label="Ожидают" value={metrics.complaints_pending} detail={`Самая старая: ${duration(metrics.oldest_complaint_pending_seconds)}`} href="/reports" />
        <MetricCard label="В работе" value={metrics.complaints_in_review} detail="IN_REVIEW и ESCALATED" href="/reports" />
        <MetricCard label="Просрочены" value={metrics.complaints_overdue} detail="По сроку из карточки жалобы" href="/reports" tone={metrics.complaints_overdue > 0 ? 'metric-alert' : ''} />
      </div></section>
      <section className="dashboard-section" aria-labelledby="operations-metrics"><div className="section-heading"><div><p className="eyebrow">ASYNC OPERATIONS</p><h2 id="operations-metrics">Операции и публикации</h2></div><a className="text-link" href="/operations/events">Открыть события →</a></div><div className="metric-grid metric-grid-four">
        <MetricCard label="Outbox в ожидании" value={metrics.outbox_pending ?? 'Нет данных'} detail="PENDING, RETRY, LEASED, WAITING_ACK" href="/operations/events" />
        <MetricCard label="Outbox dead" value={metrics.outbox_dead ?? 'Нет данных'} detail="События, требующие разбора" href="/operations/events" tone={(metrics.outbox_dead ?? 0) > 0 ? 'metric-alert' : ''} />
        <MetricCard label="Среднее время решения" value={duration(metrics.average_resolution_seconds == null ? null : Math.round(metrics.average_resolution_seconds))} detail={`${number.format(metrics.resolved_decision_count)} завершённых решений`} />
        <MetricCard label="Данные категорий" value="Нет метрики" detail="Health-агрегат не входит в текущий контракт dashboard" href="/taxonomy/categories" />
      </div></section>
      <section className="dashboard-section workload-section" aria-labelledby="workload-heading"><div className="section-heading"><div><p className="eyebrow">STAFF LOAD</p><h2 id="workload-heading">Загрузка модераторов</h2></div></div>{metrics.workload_by_moderator.length ? <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Staff ID</th><th>Заявок в работе</th><th>Очередь</th></tr></thead><tbody>{metrics.workload_by_moderator.map((item) => <tr key={item.staff_id}><th scope="row"><code>{item.staff_id}</code></th><td>{number.format(item.in_review)}</td><td><a className="text-link" href="/moderation">Открыть очередь →</a></td></tr>)}</tbody></table></div> : <div className="admin-empty"><p>API не вернул модераторов с активными заявками.</p></div>}</section>
      <details className="provenance-details"><summary>Источники и ограничения метрик</summary><dl>{Object.entries(metrics.provenance).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><p>Срез рассчитан на стороне Admin API в {dateTime(metrics.as_of)}. Тренд SLA не выдаётся как временной ряд: текущий контракт содержит только агрегаты на один момент.</p></details>
    </>}
  </>;
}
