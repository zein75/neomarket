'use client';

import { StorefrontHeaderActions } from './StorefrontHeaderActions';

type StorefrontHeaderProps = {
  active?: 'catalog' | 'favorites' | 'orders';
  favoriteCount: number | null;
  cartCount: number | null;
  accountAuthenticated?: boolean | null;
  status?: string;
  searchValue?: string;
  searchLabel?: string;
  searchPlaceholder?: string;
  onSearchChange?: (value: string) => void;
  onSearchSubmit?: () => void;
};

export function StorefrontHeader({
  active = 'catalog', favoriteCount, cartCount, accountAuthenticated = null,
  status = 'ЦЕНЫ И НАЛИЧИЕ — ИЗ КАТАЛОГА', searchValue, searchLabel = 'Поиск по каталогу',
  searchPlaceholder = 'Поиск товаров и SKU…', onSearchChange, onSearchSubmit,
}: StorefrontHeaderProps) {
  const controlledSearch = onSearchChange !== undefined;
  const accountHref = accountAuthenticated ? '/account' : '/login';
  const accountLabel = accountAuthenticated === null ? 'Аккаунт' : accountAuthenticated ? 'Мой аккаунт' : 'Войти';

  return <header className="storefront-site-header">
    <div className="storefront-system-strip">
      <div className="storefront-system-source"><span className="storefront-status-dot" aria-hidden="true" />NEOMARKET / B2C</div>
      <span className="storefront-system-data">{status}</span>
      <span className="storefront-session">{accountAuthenticated ? 'СЕССИЯ: АКТИВНА' : 'СЕССИЯ: ГОСТЬ'}</span>
    </div>
    <div className="storefront-nav-row">
      <a className="storefront-brand" href="/catalog" aria-label="NeoMarket — каталог">
        <span className="storefront-brand-mark" aria-hidden="true">N</span>
        <span className="storefront-brand-copy"><b>NEOMARKET</b><small>B2B / B2C ARCHITECTURE</small></span>
      </a>
      <nav className="storefront-main-nav" aria-label="Основная навигация">
        <a className={active === 'catalog' ? 'is-active' : ''} aria-current={active === 'catalog' ? 'page' : undefined} href="/catalog">Каталог / магазин</a>
        <a className={active === 'favorites' ? 'is-active' : ''} aria-current={active === 'favorites' ? 'page' : undefined} href="/favorites">Избранное</a>
        <a className={active === 'orders' ? 'is-active' : ''} aria-current={active === 'orders' ? 'page' : undefined} href="/account/orders">Заказы</a>
      </nav>
      <form className="storefront-header-search" action={controlledSearch ? undefined : '/catalog'} method={controlledSearch ? undefined : 'get'} role="search" onSubmit={(event) => {
        if (controlledSearch || onSearchSubmit) event.preventDefault();
        onSearchSubmit?.();
      }}>
        <span className="material-symbols-outlined" aria-hidden="true">search</span>
        <input aria-label={searchLabel} name={controlledSearch ? undefined : 'q'} type="search" value={controlledSearch ? searchValue ?? '' : undefined} onChange={controlledSearch ? (event) => onSearchChange(event.target.value) : undefined} placeholder={searchPlaceholder} />
        <kbd aria-hidden="true">⌘K</kbd>
      </form>
      <StorefrontHeaderActions favoriteCount={favoriteCount} cartCount={cartCount} />
      <a className="storefront-account-link" href={accountHref}><span className="material-symbols-outlined" aria-hidden="true">person</span><span>{accountLabel}</span></a>
    </div>
  </header>;
}
