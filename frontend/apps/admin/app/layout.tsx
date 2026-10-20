import type { Metadata } from 'next';
import './globals.css';
import './admin.css';

export const metadata: Metadata = { title: 'NeoMarket Admin Console', robots: { index: false, follow: false } };
export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="ru"><body>{children}</body></html>; }
