import type { Metadata } from 'next';
import { isCategoryDetailDto, type CategoryDetailDto } from '@neomarket/api-types';
import { CategoryDetail } from '../../../../src/CategoryDetail';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function readCategory(id: string): Promise<CategoryDetailDto | null> {
  if (process.env.NEXT_PUBLIC_ENABLE_LIVE_CATALOG !== 'true' || !uuid.test(id) || !process.env.NEOMARKET_B2C_URL) return null;
  try {
    const response = await fetch(`${process.env.NEOMARKET_B2C_URL.replace(/\/$/, '')}/api/v1/categories/${id}`, { headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!response.ok) return null;
    const payload: unknown = await response.json();
    return isCategoryDetailDto(payload) ? payload : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const origin = process.env.NEOMARKET_PUBLIC_ORIGIN ?? 'https://www.example-market.test';
  const canonical = `${origin.replace(/\/$/, '')}/catalog/category/${encodeURIComponent(id)}`;
  const category = await readCategory(id);
  const indexable = Boolean(category);
  return {
    title: category ? `${category.name} | NeoMarket` : 'Категория | NeoMarket',
    description: category?.description || 'Категория товаров NeoMarket.',
    alternates: { canonical },
    robots: { index: indexable, follow: indexable },
    openGraph: category ? { type: 'website', title: category.name, description: category.description || `Товары категории ${category.name}`, url: canonical } : undefined,
  };
}

export default async function CategoryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CategoryDetail categoryId={id} />;
}
