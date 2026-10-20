import { AdminShell } from '../../src/AdminPage';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default function Page() {
  return <AdminShell section="/bulk-operations">
    <p className="eyebrow">ADMIN CONSOLE / BULK OPERATIONS</p>
    <div className="admin-heading-row"><div><h1>Массовые операции</h1><p className="admin-intro">Изменения для набора записей начинаются с серверного dry run, показывающего точный охват, impact и исключения.</p></div></div>
    <section className="admin-panel bulk-blocked-panel"><p className="eyebrow">DRY RUN REQUIRED</p><h2>Предпросмотр недоступен</h2><div className="admin-alert"><strong>B2B bulk contracts не настроены</strong><span>503 · bulk impact preview / execution unavailable</span><p>Без подтверждённого списка объектов и результата preview нельзя выбрать цели, вычислять эффект на клиенте или отправлять предложение.</p></div><ul className="bulk-guard-list"><li>Нет выбора записей из неподтверждённого локального списка.</li><li>Нет оценки количества затронутых объектов, ошибок или необходимости повторного согласования.</li><li>Нет отправки операции и имитации её прогресса или результата.</li></ul><a className="admin-button admin-button-link" href="/settings">Открыть инвентарь интеграций</a></section>
  </AdminShell>;
}
