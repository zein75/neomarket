'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { sellerApiRequest, sellerObject, sellerString, sellerBoolean } from './lib/seller-api';

export function SellerLogoutButton() {
  const router = useRouter();
  const pathname = usePathname();
  const [authenticated, setAuthenticated] = useState(false);
  const [sessionChecked, setSessionChecked] = useState(false);
  const [logoutAllError, setLogoutAllError] = useState('');

  const decodeSession = (value: unknown) => sellerObject(value, 'session response');
  const decodeCsrf = (value: unknown) => ({ token: sellerString(sellerObject(value, 'csrf response').token, 'csrf response.token') });
  const decodeOk = (value: unknown) => {
    const object = sellerObject(value, 'logout response');
    if (!sellerBoolean(object.ok, 'logout response.ok')) throw new TypeError('logout response.ok must be true');
    return undefined;
  };

  function prepareLocalDraftExit() {
    try {
      const keys = Array.from({ length: window.sessionStorage.length }, (_, index) => window.sessionStorage.key(index))
        .filter((key): key is string => Boolean(key?.startsWith('neomarket.seller.new-product-draft.v1.')));
      if (keys.length && !window.confirm('Незавершённый черновик будет удалён из этой вкладки. Продолжить выход?')) return null;
      return keys;
    } catch {
      return [];
    }
  }

  function clearLocalDrafts(keys: string[]) {
    for (const key of keys) window.sessionStorage.removeItem(key);
  }

  useEffect(() => {
    let active = true;
    sellerApiRequest('/api/seller/auth/session', { credentials: 'same-origin', cache: 'no-store' }, decodeSession)
      .then(() => { if (active) setAuthenticated(true); })
      .catch(() => { if (active) setAuthenticated(false); })
      .finally(() => { if (active) setSessionChecked(true); });
    return () => { active = false; };
  }, [pathname]);

  async function logout() {
    const localDraftKeys = prepareLocalDraftExit();
    if (localDraftKeys === null) return;
    try {
      const payload = await sellerApiRequest('/api/seller/auth/csrf', { credentials: 'same-origin', cache: 'no-store' }, decodeCsrf);
      await sellerApiRequest('/api/seller/auth/logout', { method: 'POST', credentials: 'same-origin', headers: { Accept: 'application/json', 'X-CSRF-Token': payload.token } }, decodeOk, { retryRead: false });
    } catch { /* redirect even if the session has already expired */ }
    clearLocalDrafts(localDraftKeys);
    router.replace('/login'); router.refresh();
  }
  async function logoutAll() {
    const localDraftKeys = prepareLocalDraftExit();
    if (localDraftKeys === null) return;
    setLogoutAllError('');
    try {
      const payload = await sellerApiRequest('/api/seller/auth/csrf', { credentials: 'same-origin', cache: 'no-store' }, decodeCsrf);
      await sellerApiRequest('/api/seller/auth/logout-all', { method: 'POST', credentials: 'same-origin', headers: { Accept: 'application/json', 'X-CSRF-Token': payload.token } }, decodeOk, { retryRead: false });
      clearLocalDrafts(localDraftKeys);
      router.replace('/login'); router.refresh();
    } catch {
      setLogoutAllError('Не удалось завершить все сессии. Повторите попытку.');
    }
  }
  if (!sessionChecked || !authenticated) return null;
  return <>
    <button className="seller-logout-all" type="button" onClick={() => void logoutAll()}>Выйти везде</button>
    <button className="seller-logout" type="button" onClick={() => void logout()}>Выйти</button>
    {logoutAllError && <p className="seller-session-error" role="alert">{logoutAllError}</p>}
  </>;
}
