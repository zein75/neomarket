'use client';

import { useState } from 'react';

export function LogoutButton() {
  const [pending, setPending] = useState(false);
  async function logout() {
    setPending(true);
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { credentials: 'include', cache: 'no-store' });
      const csrf = await csrfResponse.json() as { token?: unknown };
      if (typeof csrf.token !== 'string') throw new Error('csrf');
      const response = await fetch('/api/auth/logout', { method: 'POST', credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': csrf.token } });
      if (!response.ok) throw new Error('logout');
      window.location.assign('/login');
    } finally { setPending(false); }
  }
  return <button className="button button-secondary" type="button" onClick={() => void logout()} disabled={pending}>{pending ? 'Выходим…' : 'Выйти'}</button>;
}
