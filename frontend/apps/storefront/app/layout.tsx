import type { Metadata } from 'next';
import '../src/styles.css';
import '../src/checkout.css';
import '../src/checkout-state.css';
import '../src/checkout-brutalist.css';
import '../src/checkout-overrides.css';
import '../src/favorites-brutalist.css';
import '../src/cart-state.css';
import '../src/ui-primitives.css';
import '../src/quantity-stepper.css';
import '../src/catalog-controls.css';
import '../src/catalog-rating.css';
import '../src/catalog-card-actions.css';
import '../src/auth.css';
import '../src/product-detail.css';
import '../src/product-detail-states.css';
import '../src/category-detail.css';
import '../src/category-detail-states.css';
import '../src/legal.css';
import '../src/storefront-header.css';
import '../src/storefront-header-layout.css';

export const metadata: Metadata = {
  title: { default: 'NeoMarket — прямые поставки', template: '%s | NeoMarket' },
  description: 'Маркетплейс для розничных заказов и закупок партиями.',
  metadataBase: new URL(process.env.NEOMARKET_PUBLIC_ORIGIN ?? 'https://www.example-market.test'),
  alternates: { canonical: '/' },
  openGraph: { type: 'website', siteName: 'NeoMarket', title: 'NeoMarket', description: 'Прямые поставки и закупки партиями.' },
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}
