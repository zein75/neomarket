'use client';

import { sellerErrorMessage } from '../../../src/lib/seller-error-message';
import { sellerApiRequest, sellerObject, sellerString } from '../../../src/lib/seller-api';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

function decodeCsrf(value: unknown) {
  const result = sellerObject(value, 'csrf');
  return { token: sellerString(result.token, 'csrf.token') };
}

function decodeAcceptedInvite(value: unknown) {
  const result = sellerObject(value, 'invitation acceptance');
  if (result.status !== 'ACCEPTED') throw new TypeError('invitation acceptance.status is invalid');
  return { email: sellerString(result.email, 'invitation acceptance.email') };
}

export default function AcceptSellerInvitePage() {
  const router = useRouter();
  const [token, setToken] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const inviteToken = params.get('token') || '';
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    setToken(inviteToken);
    if (!inviteToken) setError('В ссылке нет токена приглашения. Попросите владельца отправить новое приглашение.');
  }, []);

  async function accept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError('');
    try {
      const csrf = await sellerApiRequest('/api/seller/auth/csrf', { cache: 'no-store' }, decodeCsrf);
      const result = await sellerApiRequest('/api/seller/team/invitations/accept', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.token },
        body: JSON.stringify({ email, password, token }),
      }, decodeAcceptedInvite);
      router.replace(`/login?email=${encodeURIComponent(result.email)}&invite=accepted`);
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось принять приглашение'));
    } finally {
      setPending(false);
    }
  }

  return (
    <main id="main-content" className="private-shell seller-shell">
      <a className="skip-link" href="#invite-form">К форме принятия приглашения</a>
      <div className="private-bar"><span>NEOMARKET / SELLER TEAM</span><span>Приглашение сотрудника</span></div>
      <section className="private-panel seller-auth-panel">
        <p className="eyebrow">Seller Hub</p>
        <h1>Вступить в команду</h1>
        <p>Введите email, на который пришло приглашение, и создайте пароль для входа.</p>
        <form id="invite-form" className="seller-auth-form" onSubmit={accept}>
          <label htmlFor="invite-email">Рабочий email<input id="invite-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label htmlFor="invite-password">Пароль<input id="invite-password" type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="seller-submit" type="submit" disabled={pending || !token}>{pending ? 'Принимаем приглашение…' : 'Принять приглашение'}</button>
        </form>
        <a className="seller-back" href="/login">Перейти ко входу</a>
      </section>
    </main>
  );
}
