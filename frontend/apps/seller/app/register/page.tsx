'use client';

import { sellerErrorMessage } from '../../src/lib/seller-error-message';

import { FormEvent, useState } from 'react';
import Link from 'next/link';
import { sellerApiRequest, sellerObject, sellerString } from '../../src/lib/seller-api';

export default function SellerRegisterPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [company, setCompany] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  function decodeRegistration(value: unknown): { status: 'PENDING_EMAIL'; message: string } {
    const object = sellerObject(value, 'registration response');
    if (sellerString(object.status, 'registration response.status') !== 'PENDING_EMAIL') throw new TypeError('registration response.status is invalid');
    return { status: 'PENDING_EMAIL', message: sellerString(object.message, 'registration response.message') };
  }

  function decodeResend(value: unknown): { message: string } {
    const object = sellerObject(value, 'resend response');
    return { message: sellerString(object.message, 'resend response.message') };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError('');
    setNotice('');
    try {
      const result = await sellerApiRequest('/api/seller/auth/register', {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, company_name: company }),
      }, decodeRegistration, { retryRead: false });
      setNotice(result.message);
      setPassword('');
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось создать аккаунт'));
    } finally {
      setPending(false);
    }
  }

  async function resend() {
    setPending(true);
    setError('');
    try {
      const result = await sellerApiRequest('/api/seller/auth/email-verification/resend', {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      }, decodeResend, { retryRead: false });
      setNotice(result.message);
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось отправить письмо'));
    } finally {
      setPending(false);
    }
  }

  return (
    <main id="main-content" className="private-shell seller-shell">
      <a className="skip-link" href="#register-form">К форме регистрации</a>
      <div className="private-bar"><span>NEOMARKET / SELLER HUB</span><span>Регистрация продавца</span></div>
      <section className="private-panel seller-auth-panel">
        <p className="eyebrow">Новый магазин</p>
        <h1>Начните продавать</h1>
        <p>Создайте аккаунт. Сначала подтвердите рабочую почту, затем мы проверим данные магазина.</p>
        <form id="register-form" className="seller-auth-form" onSubmit={submit}>
          <label htmlFor="register-company">Название компании
            <input id="register-company" name="company_name" autoComplete="organization" required maxLength={255} value={company} onChange={(event) => setCompany(event.target.value)} />
          </label>
          <label htmlFor="register-email">Рабочий email
            <input id="register-email" name="email" type="email" autoComplete="email" required maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label htmlFor="register-password">Пароль
            <input id="register-password" name="password" type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          {error && <button className="seller-auth-text-button" type="button" onClick={resend} disabled={pending}>Запросить письмо подтверждения</button>}
          {notice && <div className="seller-auth-success" role="status"><p>{notice}</p><button className="seller-auth-text-button" type="button" onClick={resend} disabled={pending}>Отправить ссылку ещё раз</button></div>}
          <button className="seller-submit" type="submit" disabled={pending}>{pending ? 'Создаём аккаунт…' : 'Создать аккаунт'}</button>
        </form>
        <p className="seller-auth-switch">Уже зарегистрированы? <Link href="/login">Войти</Link></p>
      </section>
    </main>
  );
}
