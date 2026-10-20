'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { SellerApiError, sellerApiRequest, sellerArray, sellerObject, sellerString, sellerBoolean } from '../../src/lib/seller-api';

type OrganizationOption = { id: string; company_name: string; role: string };

function decodeOrganization(value: unknown): OrganizationOption {
  const object = sellerObject(value, 'organization');
  return { id: sellerString(object.id, 'organization.id'), company_name: sellerString(object.company_name, 'organization.company_name'), role: sellerString(object.role, 'organization.role') };
}

function decodeLogin(value: unknown): { ok: true } {
  const object = sellerObject(value, 'login response');
  if (!sellerBoolean(object.ok, 'login response.ok')) throw new TypeError('login response.ok must be true');
  return { ok: true };
}

export default function SellerLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [inviteAccepted, setInviteAccepted] = useState(false);
  const [organizations, setOrganizations] = useState<OrganizationOption[]>([]);
  const [organizationId, setOrganizationId] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setEmail(params.get('email') || '');
    setInviteAccepted(params.get('invite') === 'accepted');
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError('');
    const body = new FormData();
    body.set('username', email);
    body.set('password', password);
    if (organizationId) body.set('seller_id', organizationId);
    try {
      await sellerApiRequest('/api/seller/auth/login', {
        method: 'POST',
        body,
        headers: { Accept: 'application/json' },
      }, decodeLogin, { retryRead: false });
      setOrganizations([]);
      const next = new URLSearchParams(window.location.search).get('next');
      router.replace(next && next.startsWith('/') && !next.startsWith('//') ? next : '/dashboard');
      router.refresh();
    } catch (cause) {
      if (cause instanceof SellerApiError && cause.status === 409 && cause.code === 'ORGANIZATION_SELECTION_REQUIRED') {
        const organizations = cause.problem?.organizations;
        if (Array.isArray(organizations)) {
          try {
            setOrganizations(sellerArray(organizations, 'organizations', decodeOrganization));
            setOrganizationId('');
          } catch { /* malformed conflict payload remains a normal login error */ }
        }
      }
      setError(cause instanceof Error ? cause.message : 'Не удалось подключиться. Проверьте соединение и повторите попытку.');
    } finally {
      setPending(false);
    }
  }

  return (
    <main id="main-content" className="private-shell seller-shell">
      <a className="skip-link" href="#login-form">К форме входа</a>
      <div className="private-bar"><span>NEOMARKET / SELLER AUTH</span><span>Защищённый вход</span></div>
      <section className="private-panel seller-auth-panel">
        <p className="eyebrow">Seller Hub</p>
        {inviteAccepted && <p className="seller-auth-success" role="status">Приглашение принято. Теперь войдите с указанным email.</p>}
        <h1>Вход продавца</h1>
        <p>Сессия хранится в защищённой HttpOnly cookie. Токен не попадает в браузерный JavaScript.</p>
        <form id="login-form" className="seller-auth-form" onSubmit={submit}>
          <label htmlFor="seller-email">Рабочий email
            <input id="seller-email" name="username" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label htmlFor="seller-password">Пароль
            <input id="seller-password" name="password" type="password" autoComplete="current-password" required minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          {organizations.length > 0 && <label htmlFor="seller-organization">Организация
            <select id="seller-organization" required value={organizationId} onChange={(event) => setOrganizationId(event.target.value)}>
              <option value="">Выберите организацию</option>
              {organizations.map((organization) => <option key={organization.id} value={organization.id}>{organization.company_name} — {organization.role}</option>)}
            </select>
          </label>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="seller-submit" type="submit" disabled={pending}>{pending ? 'Проверяем…' : 'Войти в Seller Hub'}</button>
        </form>
        <p className="seller-auth-switch">Новый продавец? <Link href="/register">Создать аккаунт</Link></p>
        <a className="seller-back" href="/">Вернуться на витрину</a>
      </section>
    </main>
  );
}
