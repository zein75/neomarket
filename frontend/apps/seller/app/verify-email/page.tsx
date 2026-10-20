'use client';

import { sellerErrorMessage } from '../../src/lib/seller-error-message';
import { sellerApiRequest, sellerObject, sellerString } from '../../src/lib/seller-api';

import { FormEvent, useEffect, useRef, useState } from 'react';
import Link from 'next/link';

function decodeVerificationResult(value: unknown) {
  const result = sellerObject(value, 'email verification');
  if (result.status !== 'PENDING_REVIEW') throw new TypeError('email verification.status is invalid');
  return { message: sellerString(result.message, 'email verification.message') };
}

function decodeResendResult(value: unknown) {
  const result = sellerObject(value, 'verification resend');
  return { message: sellerString(result.message, 'verification resend.message') };
}

export default function VerifySellerEmailPage() {
  const started = useRef(false);
  const [email, setEmail] = useState('');
  const [notice, setNotice] = useState('Проверяем ссылку…');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const url = new URL(window.location.href);
    const token = new URLSearchParams(url.hash.slice(1)).get('token') || '';
    window.history.replaceState(null, '', '/verify-email');
    if (!token) {
      setNotice('');
      setError('В ссылке нет кода подтверждения. Запросите новое письмо.');
      return;
    }
    void (async () => {
      try {
        const result = await sellerApiRequest('/api/seller/auth/verify-email', {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        }, decodeVerificationResult);
        setNotice(result.message);
      } catch (cause) {
        setNotice('');
        setError(sellerErrorMessage(cause, 'Не удалось подтвердить email'));
      }
    })();
  }, []);

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError('');
    try {
      const result = await sellerApiRequest('/api/seller/auth/email-verification/resend', {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      }, decodeResendResult);
      setNotice(result.message);
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось отправить письмо'));
    } finally {
      setPending(false);
    }
  }

  return (
    <main id="main-content" className="private-shell seller-shell">
      <a className="skip-link" href="#verification-result">К результату подтверждения</a>
      <div className="private-bar"><span>NEOMARKET / SELLER HUB</span><span>Подтверждение email</span></div>
      <section id="verification-result" className="private-panel seller-auth-panel" aria-live="polite">
        <p className="eyebrow">Проверка адреса</p>
        <h1>Email продавца</h1>
        {notice && <p className="seller-auth-success" role="status">{notice}</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        {error && <form className="seller-auth-form" onSubmit={resend}>
          <label htmlFor="resend-email">Рабочий email
            <input id="resend-email" type="email" autoComplete="email" required maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <button className="seller-submit" type="submit" disabled={pending}>{pending ? 'Отправляем…' : 'Запросить новую ссылку'}</button>
        </form>}
        <Link className="seller-back" href="/login">Перейти ко входу</Link>
      </section>
    </main>
  );
}
