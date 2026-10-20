import type { Metadata } from 'next';
import { isProductDetailDto, normalizeProductDetail, type ProductDetailDto } from '@neomarket/api-types';
import { ProductDetail } from '../../../src/ProductDetail';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function readProduct(id: string): Promise<ProductDetailDto | null> {
  if (process.env.NEXT_PUBLIC_ENABLE_LIVE_CATALOG !== 'true' || !uuid.test(id) || !process.env.NEOMARKET_B2C_URL) return null;
  try {
    const response = await fetch(`${process.env.NEOMARKET_B2C_URL.replace(/\/$/, '')}/api/v1/catalog/${id}`, { headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!response.ok) return null;
    const payload: unknown = await response.json();
    return isProductDetailDto(payload) ? normalizeProductDetail(payload) : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const origin = process.env.NEOMARKET_PUBLIC_ORIGIN ?? 'https://www.example-market.test';
  const canonical = `${origin.replace(/\/$/, '')}/product/${encodeURIComponent(id)}`;
  const product = await readProduct(id);
  const indexable = Boolean(product && (product.availability ? product.availability === 'available' : product.in_stock !== false));
  return {
    // The root title template appends the single site brand suffix.
    title: product ? product.title : 'Карточка товара',
    description: product ? `Актуальная информация о товаре ${product.title} в NeoMarket.` : 'Карточка товара NeoMarket доступна после проверки каталога.',
    alternates: { canonical },
    robots: { index: indexable, follow: indexable },
    openGraph: product ? { type: 'website', title: product.title, description: `Товар ${product.title} в NeoMarket`, url: canonical, images: product.image ? [{ url: product.image, alt: product.title }] : undefined } : undefined,
  };
}

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProductDetail productId={id} />;
}
