'use client';

import { useEffect, useState } from 'react';
import { isCategoryDetailDto, type CategoryDetailDto } from '@neomarket/api-types';

export function CategoryDetail({ categoryId }: { categoryId: string }) {
  const [state, setState] = useState<'loading' | 'ready' | 'error' | 'disabled'>(process.env.NEXT_PUBLIC_ENABLE_LIVE_CATALOG === 'true' ? 'loading' : 'disabled');
  const [category, setCategory] = useState<CategoryDetailDto | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_ENABLE_LIVE_CATALOG !== 'true') return;
    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 4000);
    fetch(`/api/storefront/categories/${encodeURIComponent(categoryId)}`, { signal: controller.signal, headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(async (response) => { if (!response.ok) throw new Error(`category_${response.status}`); return response.json(); })
      .then((value: unknown) => { if (!isCategoryDetailDto(value)) throw new Error('invalid_category'); setCategory(value); setState('ready'); })
      .catch((error: unknown) => { if (error instanceof DOMException && error.name === 'AbortError') { if (timedOut) setState('error'); return; } setState('error'); });
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [categoryId, retryNonce]);
  if (state === 'loading') return <main className="category-detail-skeleton" aria-busy="true" aria-label="Загрузка категории"><p className="eyebrow">SF-03 / CATEGORY</p><div className="category-skeleton-title" /><div className="category-skeleton-copy" /><div className="inline-state" role="status">Загружаем authoritative категорию…</div></main>;
  if (state === 'disabled') return <main className="content-section"><p className="eyebrow">SF-03 / CATEGORY</p><h1>Категория</h1><div className="empty-state"><h3>Категория доступна после подключения каталога</h3><p>Preview не придумывает название, описание и product count.</p></div></main>;
  if (state === 'error' || !category) return <main className="content-section"><p className="eyebrow">SF-03 / CATEGORY</p><h1>Категория недоступна</h1><div className="empty-state"><h3>Authoritative данные не получены</h3><p>Повторите безопасный GET-запрос или вернитесь в каталог.</p><div className="category-error-actions"><button className="button button-primary" type="button" onClick={() => { setState('loading'); setRetryNonce((value) => value + 1); }}>Повторить запрос</button><a className="button button-secondary" href="/catalog">Вернуться в каталог</a></div></div></main>;
  const structuredData = { '@context': 'https://schema.org', '@type': 'CollectionPage', name: category.name, description: category.description, ...(typeof category.product_count === 'number' ? { numberOfItems: category.product_count } : {}) };
  return <><script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} /><main className="content-section category-detail"><p className="eyebrow">SF-03 / CATEGORY</p><h1>{category.name}</h1>{category.description && <p className="section-copy">{category.description}</p>}{typeof category.product_count === 'number' && <span className="category-count">{category.product_count} товаров</span>}</main></>;
}
