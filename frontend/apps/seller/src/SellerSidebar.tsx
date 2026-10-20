'use client';

import type { ReactNode } from 'react';

import { SellerNavigation } from './SellerNavigation';

export type SellerSidebarLink = {
  href: string;
  label: string;
};

const SIDEBAR_LINKS = {
  dashboard: [
    { href: '/dashboard', label: 'Обзор склада' },
    { href: '/products', label: 'Товары' },
    { href: '/inventory', label: 'Управление остатками' },
    { href: '/orders', label: 'Заказы' },
    { href: '/finance', label: 'Финансы' },
    { href: '/moderation', label: 'Модерация' },
    { href: '/team', label: 'Команда' },
  ],
  catalog: [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/products', label: 'Products' },
    { href: '/inventory', label: 'Inventory' },
    { href: '/orders', label: 'Заказы' },
    { href: '/moderation', label: 'Moderation' },
  ],
  inventory: [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/products', label: 'Products' },
    { href: '/inventory', label: 'Inventory' },
    { href: '/imports', label: 'Inventory import' },
    { href: '/orders', label: 'Заказы' },
    { href: '/moderation', label: 'Moderation' },
  ],
  orders: [
    { href: '/dashboard', label: 'Главная' },
    { href: '/products', label: 'Товары' },
    { href: '/inventory', label: 'Склад' },
    { href: '/orders', label: 'Заказы' },
    { href: '/moderation', label: 'Модерация' },
  ],
  dev: [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/products', label: 'Products' },
    { href: '/inventory', label: 'Inventory' },
    { href: '/orders', label: 'Заказы' },
    { href: '/moderation', label: 'Moderation' },
  ],
  blocked: [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/products', label: 'Products' },
    { href: '/inventory', label: 'Inventory' },
    { href: '/moderation', label: 'Moderation' },
  ],
  full: [
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/products', label: 'Products' },
  { href: '/inventory', label: 'Inventory' },
  { href: '/imports', label: 'Inventory import' },
  { href: '/orders', label: 'Заказы' },
  { href: '/finance', label: 'Финансы' },
  { href: '/moderation', label: 'Moderation' },
  { href: '/team', label: 'Команда' },
  ],
} satisfies Record<string, SellerSidebarLink[]>;

export function SellerSidebar({
  activePath,
  badge = 'OWNER-SCOPED API',
  links,
  variant = 'full',
  brandSmall = 'SELLER HUB',
  ariaLabel = 'Seller navigation',
  tenant,
  footer,
}: {
  activePath?: string;
  badge?: string;
  links?: SellerSidebarLink[];
  variant?: keyof typeof SIDEBAR_LINKS;
  brandSmall?: string;
  ariaLabel?: string;
  tenant?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <aside className="seller-sidebar">
      <a className="seller-brand" href="/">
        NEOMARKET
        <small>{brandSmall}</small>
      </a>
      {tenant}
      <SellerNavigation ariaLabel={ariaLabel}>
        {(links ?? SIDEBAR_LINKS[variant] ?? SIDEBAR_LINKS.full).map((link) => (
          <a key={link.href} href={link.href} aria-current={activePath === link.href ? 'page' : undefined}>
            {link.label}
          </a>
        ))}
      </SellerNavigation>
      <span className="status-badge">{badge}</span>
      {footer}
    </aside>
  );
}
