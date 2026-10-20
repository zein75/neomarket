'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import { sellerApiRequest, sellerArray, sellerBoolean, sellerNumber, sellerObject, sellerString } from './lib/seller-api';

import { useEffect, useState } from 'react';

type Sku = { id: string; name: string; article?: string | null; price: number; stock_quantity: number; active_quantity: number; reserved_quantity: number; is_active: boolean };

function decodeSkus(value: unknown): Sku[] {
  return sellerArray(value, 'skus', (entry) => {
    const row = sellerObject(entry, 'sku');
    const article = row.article;
    if (article !== undefined && article !== null && typeof article !== 'string') throw new TypeError('sku.article must be a string or null');
    return {
      id: sellerString(row.id, 'sku.id'), name: sellerString(row.name, 'sku.name'), ...(article !== undefined ? { article: article as string | null } : {}),
      price: sellerNumber(row.price, 'sku.price'), stock_quantity: sellerNumber(row.stock_quantity, 'sku.stock_quantity'),
      active_quantity: sellerNumber(row.active_quantity, 'sku.active_quantity'), reserved_quantity: sellerNumber(row.reserved_quantity, 'sku.reserved_quantity'),
      is_active: sellerBoolean(row.is_active, 'sku.is_active'),
    };
  });
}


export function SkusPage({ productId }: { productId: string }) {
  const [items, setItems] = useState<Sku[]>([]);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');

  const load = () => {
    setPending(true);
    setError('');
    void sellerApiRequest(`/api/seller/products/${productId}/skus`, { cache: 'no-store' }, decodeSkus)
      .then(setItems)
      .catch((cause) => setError(sellerErrorMessage(cause, 'Не удалось загрузить SKU')))
      .finally(() => setPending(false));
  };

  useEffect(() => { load(); }, [productId]);

  return <main className="seller-app" id="main-content">
    <SellerSidebar variant="catalog" activePath="/products" badge="READ-ONLY SKU" />
    <section className="seller-content">
      <div className="private-bar"><span>SELLER / SKU</span><span>SERVER DATA ONLY</span></div>
      <p className="eyebrow">SELLER HUB / SE-08</p>
      <h1>SKU</h1>
      <p className="seller-intro">Цены и остатки приходят из owner-scoped B2B API. Изменение SKU появится после подтверждения upload/revision workflow.</p>
      {pending && <p className="seller-state" role="status">Загружаем SKU…</p>}
      {error && <div className="seller-state seller-error" role="alert"><strong>{error}</strong><button className="seller-submit" type="button" onClick={load}>Повторить</button><a className="seller-submit" href={`/products/${productId}`}>Назад к товару</a></div>}
      {!pending && !error && items.length === 0 && <div className="seller-state"><h2>SKU ещё не добавлены</h2><a className="seller-submit" href={`/products/${productId}`}>Назад к товару</a></div>}
      {!pending && !error && items.length > 0 && <div className="seller-table-wrap" tabIndex={0}>
        <table className="seller-table"><caption className="sr-only">SKU товара</caption><thead><tr><th>Название</th><th>Артикул</th><th>Цена</th><th>На складе</th><th>Доступно</th><th>Резерв</th><th>Статус</th></tr></thead>
          <tbody>{items.map((sku) => <tr key={sku.id}><th scope="row">{sku.name}</th><td>{sku.article || '—'}</td><td>{sku.price}</td><td>{sku.stock_quantity}</td><td>{sku.active_quantity}</td><td>{sku.reserved_quantity}</td><td><span className="status-badge">{sku.is_active ? 'ACTIVE' : 'INACTIVE'}</span></td></tr>)}</tbody>
        </table>
      </div>}
    </section>
  </main>;
}
