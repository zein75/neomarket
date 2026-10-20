'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';

const navigation = [
  ['/dashboard', 'Обзор'],
  ['/moderation', 'Модерация'],
  ['/reports', 'Жалобы'],
  ['/operations', 'Согласования'],
  ['/operations/events', 'События'],
  ['/audit', 'Аудит'],
  ['/reasons', 'Причины блокировки'],
  ['/taxonomy/categories', 'Категории'],
  ['/taxonomy/attributes', 'Атрибуты'],
  ['/appeals', 'Апелляции'],
  ['/settings', 'Настройки'],
  ['/admin-users', 'Доступы'],
  ['/products', 'Товары'],
  ['/sellers', 'Продавцы'],
  ['/taxonomy/brands', 'Бренды'],
  ['/bulk-operations', 'Массовые операции'],
] as const;

type Principal = { staff_id: string; roles: string[]; permissions: string[]; mfa_verified: boolean; session_expires_at: string | null };

async function errorMessage(response: Response) {
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown; detail?: unknown } | null;
  const detail = body?.detail;
  if (typeof body?.message === 'string') return body.message;
  if (typeof detail === 'object' && detail && 'message' in detail && typeof detail.message === 'string') return detail.message;
  if (typeof body?.code === 'string') return body.code;
  if (typeof detail === 'object' && detail && 'code' in detail && typeof detail.code === 'string') return detail.code;
  return typeof detail === 'string' ? detail : `HTTP ${response.status}`;
}

function formatDate(value: string | null) {
  if (!value) return 'Срок не указан';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Срок не распознан' : new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

const detailLabels: Record<string, string> = {
  '/moderation': 'Карточка заявки',
  '/reports': 'Карточка жалобы',
  '/appeals': 'Карточка апелляции',
  '/admin-users': 'Карточка сотрудника',
  '/products': 'Карточка товара',
  '/sellers': 'Карточка продавца',
};

export function AdminShell({ section, children }: { section: string; children: React.ReactNode }) {
  const pathname = usePathname() || section;
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [principalState, setPrincipalState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [accountError, setAccountError] = useState('');
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const menuToggleRef = useRef<HTMLButtonElement>(null);
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const drawerWasOpen = useRef(false);
  const logoutKey = useRef<string | null>(null);

  const currentNav = useMemo(() => [...navigation]
    .filter(([href]) => pathname === href || pathname.startsWith(`${href}/`))
    .sort(([a], [b]) => b.length - a.length)[0] ?? navigation.find(([href]) => href === section) ?? navigation[0], [pathname, section]);
  const searchResults = useMemo(() => {
    const value = query.trim().toLocaleLowerCase('ru');
    if (!value) return [];
    return navigation.filter(([href, label]) => `${label} ${href}`.toLocaleLowerCase('ru').includes(value)).slice(0, 6);
  }, [query]);
  const detailCrumb = pathname.startsWith(`${currentNav[0]}/`) ? detailLabels[currentNav[0]] ?? decodeURIComponent(pathname.split('/').at(-1) ?? '') : '';

  useEffect(() => {
    let active = true;
    void fetch('/api/admin/v1/me', { cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(async (response) => {
        if (!response.ok) throw new Error(await errorMessage(response));
        const data = await response.json() as Principal;
        if (active) { setPrincipal(data); setPrincipalState('ready'); setAccountError(''); }
      })
      .catch((caught) => {
        if (active) { setPrincipal(null); setPrincipalState('error'); setAccountError(caught instanceof Error ? caught.message : 'Профиль сессии недоступен'); }
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setSearchOpen(true); searchRef.current?.focus();
      }
      if (event.key === 'Escape') { setSearchOpen(false); setDrawerOpen(false); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!drawerOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [drawerOpen]);

  useEffect(() => {
    if (drawerOpen) {
      drawerWasOpen.current = true;
      drawerCloseRef.current?.focus();
    } else if (drawerWasOpen.current) {
      drawerWasOpen.current = false;
      menuToggleRef.current?.focus();
    }
  }, [drawerOpen]);

  const logout = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLogoutBusy(true); setLogoutError('');
    logoutKey.current ??= crypto.randomUUID();
    try {
      const response = await fetch('/api/admin/v1/session/logout', {
        method: 'POST', cache: 'no-store', headers: { Accept: 'application/json', 'Idempotency-Key': logoutKey.current },
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      logoutKey.current = null;
      window.location.assign('/login');
    } catch (caught) {
      setLogoutError(caught instanceof Error ? caught.message : 'Выход не подтверждён. Повторите запрос.');
    } finally { setLogoutBusy(false); }
  };

  const chooseResult = () => {
    const firstResult = searchResults.at(0);
    if (firstResult) window.location.assign(firstResult[0]);
    setSearchOpen(false);
  };

  return <main className="admin-app" id="main-content">
    <a className="skip-link" href="#admin-page-content">Перейти к содержимому</a>
    {drawerOpen && <button className="admin-drawer-backdrop" type="button" aria-label="Закрыть меню" onClick={() => setDrawerOpen(false)} />}
    <aside className="admin-sidebar" data-open={drawerOpen} aria-label="Основная навигация">
      <div className="admin-sidebar-head"><a className="admin-brand" href="/dashboard">NEOMARKET<small>ADMIN CONSOLE</small></a><button ref={drawerCloseRef} className="admin-drawer-close" type="button" aria-label="Закрыть меню" onClick={() => setDrawerOpen(false)}>×</button></div>
      <nav id="main-navigation" aria-label="Навигация администратора">
        {navigation.map(([href, label]) => <a href={href} key={href} aria-current={pathname === href || pathname.startsWith(`${href}/`) ? 'page' : undefined} onClick={() => setDrawerOpen(false)}>{label}</a>)}
      </nav>
      <span className="status-badge">{principalState === 'ready' && principal?.mfa_verified ? 'MFA подтверждена' : 'ТРЕБУЕТСЯ OIDC + MFA'}</span>
    </aside>
    <section className="admin-content" id="admin-page-content" tabIndex={-1}>
      <header className="admin-topbar">
        <button ref={menuToggleRef} className="admin-menu-toggle" type="button" aria-label="Открыть меню" aria-expanded={drawerOpen} aria-controls="main-navigation" onClick={() => setDrawerOpen(true)}>☰</button>
        <nav className="admin-breadcrumbs" aria-label="Путь страницы"><a href="/dashboard">Админ</a><span aria-hidden="true">/</span><a href={currentNav[0]} aria-current={!detailCrumb ? 'page' : undefined}>{currentNav[1]}</a>{detailCrumb && <><span aria-hidden="true">/</span><span aria-current="page">{detailCrumb}</span></>}</nav>
        <form className="admin-global-search" role="search" onSubmit={(event) => { event.preventDefault(); chooseResult(); }}>
          <label className="visually-hidden" htmlFor="admin-quick-search">Быстрый переход по разделам</label>
          <input id="admin-quick-search" ref={searchRef} type="search" value={query} onFocus={() => setSearchOpen(true)} onChange={(event) => { setQuery(event.target.value); setSearchOpen(true); }} onKeyDown={(event) => { if (event.key === 'Escape') setSearchOpen(false); }} placeholder="Поиск по разделам…" aria-controls={searchOpen && query.trim() ? 'admin-search-results' : undefined} aria-expanded={searchOpen && searchResults.length > 0} aria-autocomplete="list" />
          <kbd aria-hidden="true">Ctrl K</kbd>
          {searchOpen && query.trim() && <div className="admin-search-results" id="admin-search-results" role="group" aria-label="Разделы">
            {searchResults.length ? searchResults.map(([href, label]) => <a key={href} href={href} onClick={() => { setQuery(''); setSearchOpen(false); }}>{label}<small>{href}</small></a>) : <p>Разделы не найдены</p>}
          </div>}
        </form>
        <details className="admin-account">
          <summary aria-label="Открыть меню учётной записи"><span className="admin-account-mark" aria-hidden="true">{principal?.staff_id.slice(0, 1).toUpperCase() ?? '·'}</span><span className="admin-account-label">{principalState === 'loading' ? 'Загрузка сессии' : principal?.staff_id ?? 'Нет активной сессии'}</span><span aria-hidden="true">⌄</span></summary>
          <section className="admin-account-menu" aria-label="Учётная запись">
            {principal ? <><div className="admin-account-principal"><span className="eyebrow">ТЕКУЩИЙ СОТРУДНИК</span><code>{principal.staff_id}</code><span>{principal.roles.join(', ') || 'Роль не назначена'}</span><span>{principal.mfa_verified ? 'MFA подтверждена' : 'MFA не подтверждена'}</span><span>Сессия до {formatDate(principal.session_expires_at)}</span></div><details className="admin-permission-list"><summary>Разрешения · {principal.permissions.length}</summary><ul>{principal.permissions.map((permission) => <li key={permission}><code>{permission}</code></li>)}</ul></details></> : <p role={principalState === 'error' ? 'alert' : 'status'}>{principalState === 'error' ? accountError : 'Получаем данные сессии…'}</p>}
            {logoutError && <p className="admin-account-error" role="alert">{logoutError}</p>}
            <form onSubmit={(event) => void logout(event)}><button className="admin-button" type="submit" disabled={logoutBusy || !principal}>{logoutBusy ? 'Завершение сессии…' : 'Выйти из Admin'}</button></form>
          </section>
        </details>
      </header>
      {children}
    </section>
  </main>;
}

export function AdminPage({ section, detail }: { section: string; detail: string }) {
  return <AdminShell section={section}><p className="eyebrow">ADMIN CONSOLE / {section.toUpperCase()}</p><h1>{section}</h1><div className="admin-locked" role="status"><h2>Доступ закрыт до настройки identity</h2><p>{detail}</p><span className="status-badge">БЕЗ ДЕМО ДАННЫХ</span></div></AdminShell>;
}
