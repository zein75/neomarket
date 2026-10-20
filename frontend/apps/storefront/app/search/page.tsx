import { Storefront } from '../../src/Storefront';

export const metadata = { title: 'Поиск', robots: { index: false, follow: true } };

export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string; category?: string; sort?: string; page?: string }> }) {
  const params = await searchParams;
  const sort = params.sort === 'price_asc' || params.sort === 'price_desc' || params.sort === 'new' ? params.sort : 'popularity';
  const parsedPage = Number(params.page ?? '1');
  const page = Number.isInteger(parsedPage) && parsedPage >= 1 && parsedPage <= 10000 ? parsedPage : 1;
  return <Storefront initialView="catalog" initialQuery={typeof params.q === 'string' ? params.q.slice(0, 200) : ''} initialCategory={typeof params.category === 'string' ? params.category.slice(0, 100) : ''} initialSort={sort} initialPage={page} />;
}
