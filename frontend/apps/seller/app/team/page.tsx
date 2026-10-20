'use client';
import { SellerSidebar } from '../../src/SellerSidebar';

import { sellerErrorMessage } from '../../src/lib/seller-error-message';
import { SellerApiError, sellerApiRequest, sellerArray, sellerBoolean, sellerInteger, sellerObject, sellerString } from '../../src/lib/seller-api';

import { FormEvent, useEffect, useState } from 'react';

type Role = 'MANAGER' | 'CATALOG_EDITOR' | 'WAREHOUSE_OPERATOR' | 'SUPPORT' | 'FINANCE' | 'VIEWER';
type Member = { id: string; email: string; role: string; active: boolean; created_at: string; revision: number };
type Problem = { title?: string };

function decodeCsrf(value: unknown) {
  const result = sellerObject(value, 'csrf');
  return { token: sellerString(result.token, 'csrf.token') };
}

function decodeMember(value: unknown): Member {
  const member = sellerObject(value, 'member');
  return {
    id: sellerString(member.id, 'member.id'),
    email: sellerString(member.email, 'member.email'),
    role: sellerString(member.role, 'member.role'),
    active: sellerBoolean(member.active, 'member.active'),
    created_at: sellerString(member.created_at, 'member.created_at'),
    revision: sellerInteger(member.revision, 'member.revision'),
  };
}

function decodeMembers(value: unknown): Member[] {
  return sellerArray(value, 'members', decodeMember);
}

function decodeInvitation(value: unknown) {
  const invitation = sellerObject(value, 'invitation');
  return {
    expires_at: sellerString(invitation.expires_at, 'invitation.expires_at'),
  };
}

function decodeEmpty(value: unknown): undefined {
  if (value !== undefined) throw new TypeError('expected an empty response');
  return undefined;
}

const roleLabels: Record<Role, string> = {
  MANAGER: 'Менеджер',
  CATALOG_EDITOR: 'Редактор каталога',
  WAREHOUSE_OPERATOR: 'Склад',
  SUPPORT: 'Поддержка',
  FINANCE: 'Финансы',
  VIEWER: 'Только просмотр',
};

export default function SellerTeamPage() {
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('VIEWER');
  const [busy, setBusy] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [memberRoles, setMemberRoles] = useState<Record<string, Role>>({});
  const [memberReasons, setMemberReasons] = useState<Record<string, string>>({});
  const [savingMember, setSavingMember] = useState<string | null>(null);

  async function loadMembers() {
    setBusy(true);
    setError('');
    try {
      const body = await sellerApiRequest('/api/seller/team/members', { cache: 'no-store' }, decodeMembers);
      setMembers(body);
      setMemberRoles(Object.fromEntries(body.map((member) => [member.id, member.role as Role])));
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось загрузить команду'));
    } finally {
      setBusy(false);
    }
  }

  async function updateMember(member: Member) {
    const nextRole = memberRoles[member.id];
    const reason = memberReasons[member.id]?.trim() || '';
    if (!nextRole || nextRole === member.role || reason.length < 3) {
      setError('Укажите новую роль и причину не короче 3 символов.');
      return;
    }
    await mutateMember(member, 'PATCH', { role: nextRole, reason });
  }

  async function revokeMember(member: Member) {
    const reason = memberReasons[member.id]?.trim() || '';
    if (reason.length < 3) {
      setError('Укажите причину отзыва доступа не короче 3 символов.');
      return;
    }
    await mutateMember(member, 'DELETE', { reason });
  }

  async function mutateMember(member: Member, method: 'PATCH' | 'DELETE', body: object) {
    setSavingMember(member.id);
    setError('');
    setNotice('');
    try {
      const csrf = await sellerApiRequest('/api/seller/auth/csrf', { cache: 'no-store' }, decodeCsrf);
      await sellerApiRequest(`/api/seller/team/members/${member.id}`, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrf.token,
          'If-Match': `"${member.revision}"`,
        },
        body: JSON.stringify(body),
      }, method === 'DELETE' ? decodeEmpty : decodeMember);
      setNotice(method === 'PATCH' ? 'Роль участника обновлена. Его активные сессии завершены.' : 'Доступ участника отозван, его активные сессии завершены.');
      setMemberReasons((current) => ({ ...current, [member.id]: '' }));
      await loadMembers();
    } catch (cause) {
      if (cause instanceof SellerApiError && cause.status === 412) {
        await loadMembers();
        setError('Данные участника изменились. Список обновлён, повторите действие.');
      } else {
        setError(sellerErrorMessage(cause, 'Не удалось изменить доступ участника'));
      }
    } finally {
      setSavingMember(null);
    }
  }

  useEffect(() => { void loadMembers(); }, []);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSending(true);
    setError('');
    setNotice('');
    try {
      const csrf = await sellerApiRequest('/api/seller/auth/csrf', { cache: 'no-store' }, decodeCsrf);
      const body = await sellerApiRequest('/api/seller/team/invitations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.token },
        body: JSON.stringify({ email, role }),
      }, decodeInvitation);
      setEmail('');
      setNotice(`Приглашение отправлено. Оно действует до ${body?.expires_at ? new Date(body.expires_at).toLocaleString('ru-RU') : 'истечения срока действия'}.`);
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось отправить приглашение'));
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="seller-app seller-dashboard" id="main-content">
      <SellerSidebar activePath="/team" ariaLabel="Seller navigation" />
      <section className="seller-content seller-dashboard-content seller-team-content">
        <div className="seller-topbar"><div><span className="eyebrow">NEOMARKET / SELLER HUB</span><strong>Доступы и роли</strong></div></div>
        <header className="seller-dashboard-heading"><div><p className="eyebrow">SELLER / ACCESS</p><h1>Команда</h1></div></header>
        <p className="seller-muted">Приглашение отправляется на email. Ссылка действует 72 часа и принимается один раз.</p>
        {error && <p className="seller-state seller-error" role="alert">{error}</p>}
        {notice && <p className="seller-auth-success" role="status">{notice}</p>}
        <section className="seller-team-layout" aria-label="Управление командой">
          <form className="seller-team-invite seller-blocked" onSubmit={invite}>
            <h2>Пригласить сотрудника</h2>
            <label htmlFor="team-email">Рабочий email<input id="team-email" type="email" autoComplete="email" required maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            <label htmlFor="team-role">Роль<select id="team-role" value={role} onChange={(event) => setRole(event.target.value as Role)}>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <button className="seller-submit" type="submit" disabled={sending}>{sending ? 'Отправляем…' : 'Отправить приглашение'}</button>
          </form>
          <section className="seller-team-members" aria-labelledby="team-members-heading">
            <div className="seller-team-heading"><h2 id="team-members-heading">Участники</h2><button className="seller-team-refresh" type="button" onClick={() => void loadMembers()} disabled={busy}>Обновить</button></div>
            {busy ? <p className="seller-state" role="status">Загружаем участников…</p> : error ? null : members.length === 0 ? <p className="seller-state">В команде пока нет участников.</p> : <div className="seller-table-wrap" tabIndex={0}><table className="seller-table"><thead><tr><th scope="col">Email</th><th scope="col">Роль</th><th scope="col">Статус</th><th scope="col">Управление</th></tr></thead><tbody>{members.map((member) => <tr key={member.id}><td>{member.email}</td><td>{roleLabels[member.role as Role] || member.role}</td><td>{member.active ? 'Активен' : 'Отключён'}</td><td>{member.role === 'OWNER' || !member.active ? <span>—</span> : <div className="seller-team-member-actions"><label className="seller-team-member-role">Новая роль<select aria-label={`Новая роль участника ${member.email}`} value={memberRoles[member.id] || (member.role as Role)} onChange={(event) => setMemberRoles((current) => ({ ...current, [member.id]: event.target.value as Role }))}>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="seller-team-member-reason">Причина<input aria-label={`Причина изменения доступа ${member.email}`} minLength={3} maxLength={500} value={memberReasons[member.id] || ''} onChange={(event) => setMemberReasons((current) => ({ ...current, [member.id]: event.target.value }))} /></label><button type="button" className="seller-submit" disabled={savingMember === member.id || memberRoles[member.id] === member.role} onClick={() => void updateMember(member)}>{savingMember === member.id ? 'Сохраняем…' : 'Сохранить роль'}</button><button type="button" className="seller-secondary" disabled={savingMember === member.id} onClick={() => void revokeMember(member)}>Отозвать доступ</button></div>}</td></tr>)}</tbody></table></div>}
          </section>
        </section>
      </section>
    </main>
  );
}
