'use client';

import { sellerErrorMessage } from './lib/seller-error-message';
import { sellerApiRequest, sellerArray, sellerBoolean, sellerObject, sellerString } from './lib/seller-api';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';

type Organization = { id: string; company_name: string; role: string; current: boolean };
const sellerRoles = ['OWNER', 'MANAGER', 'CATALOG_EDITOR', 'WAREHOUSE_OPERATOR', 'SUPPORT', 'FINANCE', 'VIEWER'] as const;

function decodeOrganizations(value: unknown): Organization[] {
  return sellerArray(value, 'organizations', (value) => {
    const item = sellerObject(value, 'organization');
    const role = sellerString(item.role, 'organization.role');
    if (!sellerRoles.includes(role as (typeof sellerRoles)[number])) throw new TypeError('organization.role is invalid');
    return {
      id: sellerString(item.id, 'organization.id'),
      company_name: sellerString(item.company_name, 'organization.company_name'),
      role,
      current: sellerBoolean(item.current, 'organization.current'),
    };
  });
}

export function TenantSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selected, setSelected] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    setError('');
    void (async () => {
      try {
        const rows = await sellerApiRequest('/api/seller/auth/organizations', { cache: 'no-store' }, decodeOrganizations);
        setOrganizations(rows);
        setSelected(rows.find((item) => item.current)?.id || '');
      } catch (cause) {
        setError(sellerErrorMessage(cause, 'Не удалось загрузить список организаций'));
      }
    })();
  }, [pathname, refreshKey]);

  if (organizations.length < 2) return null;

  async function switchOrganization() {
    if (!selected || organizations.find((item) => item.id === selected)?.current) return;
    setPending(true);
    setError('');
    try {
      const csrfToken = await sellerApiRequest('/api/seller/auth/csrf', { cache: 'no-store' }, (value) =>
        sellerString(sellerObject(value, 'CSRF response').token, 'CSRF response.token'),
      );
      await sellerApiRequest('/api/seller/auth/switch-tenant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ seller_id: selected }),
      }, (value) => {
        const response = sellerObject(value, 'tenant switch response');
        if (!sellerBoolean(response.ok, 'tenant switch response.ok')) throw new TypeError('tenant switch response.ok is false');
        return true;
      });
      setOrganizations([]);
      setSelected('');
      setRefreshKey((current) => current + 1);
      router.refresh();
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось переключить организацию'));
    } finally {
      setPending(false);
    }
  }

  return <div className="seller-tenant-switcher">
    <label htmlFor="seller-tenant-select"><span>Текущая организация</span><select id="seller-tenant-select" value={selected} onChange={(event) => setSelected(event.target.value)}>{organizations.map((organization) => <option key={organization.id} value={organization.id}>{organization.company_name} · {organization.role}</option>)}</select></label>
    <button type="button" onClick={() => void switchOrganization()} disabled={pending || organizations.find((item) => item.id === selected)?.current}>{pending ? 'Переключаем…' : 'Переключить'}</button>
    {error && <span className="seller-tenant-error" role="alert">{error}</span>}
  </div>;
}
