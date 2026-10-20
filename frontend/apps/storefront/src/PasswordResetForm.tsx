'use client';

import { useState } from 'react';
import type { FormEvent } from 'react';

export function PasswordResetForm({ confirm = false, tokenPresent = true }: { confirm?: boolean; tokenPresent?: boolean }) {
  const [message, setMessage] = useState(''); const [pending, setPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); const password = String(form.get('password') ?? '');
    if (confirm && password !== String(form.get('confirmation') ?? '')) { setMessage('Пароли не совпадают.'); return; }
    setPending(true); setMessage('');
    try {
      const endpoint = confirm ? '/api/auth/reset-confirm' : '/api/auth/reset-request';
      const body = confirm ? { reset_token: new URLSearchParams(window.location.search).get('token'), new_password: password } : { email: form.get('email') };
      const response = await fetch(endpoint, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(body), cache: 'no-store' });
      if (!response.ok) throw new Error('reset');
      setMessage(confirm ? 'Пароль изменён. Теперь можно войти.' : 'Если аккаунт существует, ссылка отправлена на почту.');
    } catch { setMessage('Сервис восстановления временно недоступен.'); }
    finally { setPending(false); }
  }
  return <main className="auth-page"><div className="auth-card"><p className="eyebrow">{confirm ? 'SF-12 / RESET CONFIRM' : 'SF-11 / RESET REQUEST'}</p><h1>{confirm ? 'Новый пароль' : 'Восстановить доступ'}</h1><p className="auth-intro">{confirm ? 'Token проверяется только B2C сервисом и не сохраняется в браузере.' : 'Укажите email, чтобы запросить безопасную ссылку восстановления.'}</p>{!confirm || tokenPresent ? <form className="auth-form" onSubmit={submit}>{!confirm && <label>Email<input type="email" name="email" autoComplete="email" required /></label>}{confirm && <><label>Новый пароль<input type="password" name="password" autoComplete="new-password" required minLength={12} /></label><label>Повторите пароль<input type="password" name="confirmation" autoComplete="new-password" required minLength={12} /></label></>}<button className="button button-primary wide" type="submit" disabled={pending}>{pending ? 'Отправляем…' : 'Продолжить'}</button></form> : <div className="auth-blocked" role="alert">Ссылка восстановления отсутствует или истекла.</div>}{message && <div className="auth-blocked" role="status">{message}</div>}<p className="auth-switch"><a href="/login">Вернуться ко входу</a></p></div></main>;
}
