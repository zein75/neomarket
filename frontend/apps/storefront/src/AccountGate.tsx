'use client';

import { useEffect, useState } from 'react';
import { isSessionResponse } from '@neomarket/api-types';

type GateState = 'checking' | 'guest' | 'ready' | 'unavailable';

export function AccountGate({ section, description }: { section: string; description: string }) {
  const [state, setState] = useState<GateState>('checking');
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 4000);
    fetch('/api/auth/session', { signal: controller.signal, credentials: 'include', headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then((response) => {
        if (response.status === 503) { setState('unavailable'); return null; }
        if (response.status === 401) { setState('guest'); return null; }
        if (!response.ok) throw new Error('session');
        return response.json();
      })
      .then((payload: unknown) => {
        if (payload === null) return;
        if (!isSessionResponse(payload)) { setState('unavailable'); return; }
        setState(payload.authenticated ? 'ready' : 'guest');
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError' && !timedOut) return;
        setState('unavailable');
      });
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [retryNonce]);

  if (state === 'checking') return <main className="content-section"><div className="inline-state" role="status">Проверяем session boundary…</div></main>;
  if (state === 'ready') return <main className="content-section"><p className="eyebrow">ACCOUNT / {section.toUpperCase()}</p><h1>{section}</h1><div className="empty-state"><h3>Данные будут загружены через typed BFF</h3><p>{description}</p></div></main>;

  const unavailable = state === 'unavailable';
  return <main className="content-section"><p className="eyebrow">ACCOUNT / {section.toUpperCase()}</p><h1>{section}</h1><div className="empty-state"><h3>{unavailable ? 'Сервис session недоступен' : 'Войдите, чтобы продолжить'}</h3><p>{unavailable ? 'Приватные данные скрыты, пока результат проверки не подтверждён.' : description}</p>{unavailable ? <button className="button button-secondary" type="button" onClick={() => { setState('checking'); setRetryNonce((value) => value + 1); }}>Повторить проверку</button> : <a className="button button-primary" href="/login">Войти через server-side session</a>}</div></main>;
}
