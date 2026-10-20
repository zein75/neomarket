'use client';

import { useState } from 'react';
import type { FormEvent } from 'react';

export function AuthForm({ mode }: { mode: 'login' | 'register' }) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const isLogin = mode === 'login';

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!isLogin && form.get('password') !== form.get('passwordConfirmation')) {
      setMessage('Пароли не совпадают.');
      return;
    }
    setPending(true);
    setMessage('');
    try {
      const response = await fetch(isLogin ? '/api/auth/login' : '/api/auth/register', {
        method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ email: form.get('email'), password: form.get('password') }),
      });
      const payload = await response.json().catch(() => null) as { authenticated?: unknown } | null;
      if (!response.ok) {
        const safeMessage = isLogin && (response.status === 401 || response.status === 403)
          ? 'Неверный email или пароль.'
          : response.status === 409
            ? 'Аккаунт с такими данными уже существует.'
            : response.status === 429
              ? 'Слишком много попыток. Повторите позже.'
              : 'Сервис авторизации временно недоступен.';
        throw new Error(safeMessage);
      }
      if (!isLogin && payload?.authenticated === false) {
        window.location.assign('/login?registered=1');
        return;
      }
      window.location.assign('/catalog');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Сервис авторизации недоступен.');
      setPending(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-card">
        <p className="eyebrow">{isLogin ? 'SF-09 / SIGN IN' : 'SF-10 / REGISTER'}</p>
        <h1>{isLogin ? 'Войти в NeoMarket' : 'Создать аккаунт'}</h1>
        <p className="auth-intro">{isLogin ? 'Сессия сохраняется только в HttpOnly cookie и используется BFF для server-to-server запросов.' : 'Регистрация создаёт buyer-аккаунт в B2C сервисе.'}</p>
        <form className="auth-form" onSubmit={submit}>
          <label>Email<input type="email" name="email" autoComplete="email" required placeholder="you@example.com" /></label>
          <label>Пароль<input type="password" name="password" autoComplete={isLogin ? 'current-password' : 'new-password'} required minLength={8} /></label>
          {!isLogin && <label>Повторите пароль<input type="password" name="passwordConfirmation" autoComplete="new-password" required minLength={8} /></label>}
          <button className="button button-primary wide" type="submit" disabled={pending}>{pending ? 'Проверяем…' : isLogin ? 'Продолжить' : 'Создать аккаунт'}</button>
        </form>
        {message && <div className="auth-blocked" role="alert">{message}</div>}
        {isLogin && <p className="auth-switch"><a href="/reset-password">Забыли пароль?</a></p>}
        <p className="auth-switch">{isLogin ? 'Нет аккаунта?' : 'Уже зарегистрированы?'} <a href={isLogin ? '/register' : '/login'}>{isLogin ? 'Создать аккаунт' : 'Войти'}</a></p>
      </div>
    </main>
  );
}
