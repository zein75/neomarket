'use client';

import { useEffect, useState } from 'react';
import { isSessionResponse, type SessionResponse } from '@neomarket/api-types';
import { LogoutButton } from './LogoutButton';

export function AccountDashboard() {
  const [session, setSession] = useState<SessionResponse | null>(null); const [state, setState] = useState<'loading' | 'ready' | 'guest' | 'error'>('loading');
  useEffect(() => { const controller = new AbortController(); fetch('/api/auth/session', { credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller.signal }).then(async (response) => { const payload = await response.json().catch(() => null); if (!response.ok || !isSessionResponse(payload)) throw new Error('session'); setSession(payload); setState(payload.authenticated ? 'ready' : 'guest'); }).catch(() => setState('error')); return () => controller.abort(); }, []);
  if (state === 'loading') return <main className="content-section"><div className="inline-state" role="status">Проверяем buyer session…</div></main>;
  if (state !== 'ready' || !session?.principal) return <main className="content-section"><p className="eyebrow">ACCOUNT / PRIVATE</p><h1>Аккаунт</h1><div className="empty-state"><h3>{state === 'error' ? 'Session service недоступен' : 'Войдите, чтобы продолжить'}</h3><p>Приватные данные не показываются без подтверждённой server-side сессии.</p>{state === 'guest' && <a className="button button-primary" href="/login">Войти</a>}</div></main>;
  return <main className="content-section"><div className="section-heading"><div><p className="eyebrow">ACCOUNT / BUYER</p><h1>Личный кабинет</h1></div><LogoutButton /></div><p className="section-copy">Сессия подтверждена BFF. Все приватные запросы проверяют ownership на backend.</p><div className="catalog-section"><div className="product-grid"><a className="product-card" href="/account/orders"><span className="eyebrow">ORDERS</span><h3>Мои заказы</h3><p>История, статусы и отмена собственных заказов.</p><span className="button button-secondary">Открыть →</span></a><a className="product-card" href="/account/addresses"><span className="eyebrow">DELIVERY</span><h3>Адреса доставки</h3><p>Сохранённые адреса для checkout.</p><span className="button button-secondary">Управлять →</span></a></div></div><div className="checkout-note" role="status"><strong>BUYER ID</strong><span className="mono">{session.principal.id}</span></div></main>;
}
