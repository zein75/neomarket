'use client';
import { SellerSidebar } from '../../src/SellerSidebar';
import { SellerApiError, sellerApiRequest } from '../../src/lib/seller-api';

import { useEffect, useState } from 'react';

type FinanceState = 'loading' | 'not-configured' | 'forbidden' | 'error';

export default function FinanceUnavailable({ endpoint, title }: { endpoint: 'overview' | 'payouts'; title: string }) {
  const [state, setState] = useState<FinanceState>('loading');

  useEffect(() => {
    let active = true;
    void sellerApiRequest(`/api/seller/finance/${endpoint}`, { cache: 'no-store' }, (value) => value)
      .then(() => { if (active) setState('error'); })
      .catch((cause: unknown) => {
        if (!active) return;
        if (cause instanceof SellerApiError && cause.status === 501 && cause.code === 'FEATURE_NOT_CONFIGURED') setState('not-configured');
        else if (cause instanceof SellerApiError && cause.status === 403) setState('forbidden');
        else setState('error');
      });
    return () => { active = false; };
  }, [endpoint]);

  const messages: Record<Exclude<FinanceState, 'loading'>, string> = {
    'not-configured': 'Финансовые данные и выплаты появятся после настройки платёжного провайдера и правил комиссии. Сейчас система не располагает подтверждёнными расчётами.',
    forbidden: 'У вашей роли нет доступа к финансовому разделу.',
    error: 'Не удалось проверить состояние финансового сервиса. Попробуйте обновить страницу позже.',
  };

  return (
    <main className="seller-app seller-dashboard" id="main-content">
      <SellerSidebar
        activePath={endpoint === 'overview' ? '/finance' : '/finance/payouts'}
        ariaLabel="Seller navigation"
        links={[
          { href: '/dashboard', label: 'Dashboard' },
          { href: '/products', label: 'Products' },
          { href: '/inventory', label: 'Inventory' },
          { href: '/orders', label: 'Orders' },
          { href: '/finance', label: 'Finance' },
          { href: '/finance/payouts', label: 'Payouts' },
          { href: '/moderation', label: 'Moderation' },
          { href: '/team', label: 'Team' },
        ]}
      />
      <section className="seller-content seller-dashboard-content seller-finance-content">
        <div className="seller-topbar"><div><span className="eyebrow">NEOMARKET / SELLER HUB</span><strong>{title}</strong></div></div>
        <header className="seller-dashboard-heading"><div><p className="eyebrow">SELLER / FINANCE</p><h1>{title}</h1></div></header>
        {state === 'loading'
          ? <p className="seller-state" role="status">Проверяем доступность финансовых данных…</p>
          : <section className={`seller-finance-state ${state === 'error' || state === 'forbidden' ? 'seller-error' : ''}`} role={state === 'error' || state === 'forbidden' ? 'alert' : 'status'}>
            <h2>{state === 'not-configured' ? 'Финансовый провайдер не настроен' : state === 'forbidden' ? 'Нет доступа' : 'Раздел временно недоступен'}</h2>
            <p>{messages[state]}</p>
          </section>}
      </section>
    </main>
  );
}
