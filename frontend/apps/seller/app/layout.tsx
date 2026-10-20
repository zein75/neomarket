import type { Metadata } from 'next';
import './globals.css';
import './seller.css';
import { SellerLogoutButton } from '../src/SellerLogoutButton';
import { TenantSwitcher } from '../src/TenantSwitcher';

export const metadata: Metadata = { title: 'NeoMarket Seller Hub', robots: { index: false, follow: false } };
export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="ru"><body><a className="skip-link" href="#main-content">К содержимому</a>{children}<TenantSwitcher /><SellerLogoutButton /></body></html>; }
