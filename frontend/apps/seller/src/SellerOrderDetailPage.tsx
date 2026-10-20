'use client';
import { SellerSidebar } from './SellerSidebar';

import { sellerErrorMessage } from './lib/seller-error-message';
import { sellerApiRequest, sellerArray, sellerNumber, sellerObject, sellerString } from './lib/seller-api';

import { useEffect, useState } from 'react';

type OrderItem = {
  id: string;
  sku_id: string;
  product_id: string;
  product_title: string;
  sku_name: string;
  quantity: number;
  unit_price_minor: number;
  line_total_minor: number;
};
type Shipment = {
  id: string;
  status: 'PACKED' | 'DISPATCHED' | 'DELIVERED';
  packed_at: string;
  lines: { seller_order_item_id: string; quantity: number }[];
  carrier_operation: {
    provider: 'LOCAL_TEST';
    status: 'PENDING_PROVIDER' | 'LABEL_CREATED';
    tracking_number: string | null;
    attempts: number;
    last_error: string | null;
  } | null;
};
type Order = {
  id: string;
  currency: string;
  status: string;
  total_minor: number;
  revision: number;
  allocated_at: string;
  seller_accepted_at: string | null;
  items: OrderItem[];
  shipments: Shipment[];
};

function decodeOrder(value: unknown): Order {
  const order = sellerObject(value, 'order');
  return {
    id: sellerString(order.id, 'order.id'),
    currency: sellerString(order.currency, 'order.currency'),
    status: sellerString(order.status, 'order.status'),
    total_minor: sellerNumber(order.total_minor, 'order.total_minor'),
    revision: sellerNumber(order.revision, 'order.revision'),
    allocated_at: sellerString(order.allocated_at, 'order.allocated_at'),
    seller_accepted_at: order.seller_accepted_at === null ? null : sellerString(order.seller_accepted_at, 'order.seller_accepted_at'),
    items: sellerArray(order.items, 'order.items', (value) => {
      const item = sellerObject(value, 'order item');
      return {
        id: sellerString(item.id, 'item.id'),
        sku_id: sellerString(item.sku_id, 'item.sku_id'),
        product_id: sellerString(item.product_id, 'item.product_id'),
        product_title: sellerString(item.product_title, 'item.product_title'),
        sku_name: sellerString(item.sku_name, 'item.sku_name'),
        quantity: sellerNumber(item.quantity, 'item.quantity'),
        unit_price_minor: sellerNumber(item.unit_price_minor, 'item.unit_price_minor'),
        line_total_minor: sellerNumber(item.line_total_minor, 'item.line_total_minor'),
      };
    }),
    shipments: sellerArray(order.shipments, 'order.shipments', (value) => {
      const shipment = sellerObject(value, 'shipment');
      const shipmentStatus = sellerString(shipment.status, 'shipment.status');
      if (!['PACKED', 'DISPATCHED', 'DELIVERED'].includes(shipmentStatus)) throw new TypeError('shipment.status is invalid');
      const operation = shipment.carrier_operation;
      return {
        id: sellerString(shipment.id, 'shipment.id'),
        status: shipmentStatus as Shipment['status'],
        packed_at: sellerString(shipment.packed_at, 'shipment.packed_at'),
        lines: sellerArray(shipment.lines, 'shipment.lines', (value) => {
          const line = sellerObject(value, 'shipment line');
          return { seller_order_item_id: sellerString(line.seller_order_item_id, 'shipment line item id'), quantity: sellerNumber(line.quantity, 'shipment line quantity') };
        }),
        carrier_operation: operation === null ? null : (() => {
          const carrier = sellerObject(operation, 'carrier operation');
          const carrierStatus = sellerString(carrier.status, 'carrier operation.status');
          if (carrier.provider !== 'LOCAL_TEST' || !['PENDING_PROVIDER', 'LABEL_CREATED'].includes(carrierStatus)) throw new TypeError('carrier operation is invalid');
          return {
            provider: 'LOCAL_TEST' as const,
            status: carrierStatus as NonNullable<Shipment['carrier_operation']>['status'],
            tracking_number: carrier.tracking_number === null ? null : sellerString(carrier.tracking_number, 'carrier operation.tracking_number'),
            attempts: sellerNumber(carrier.attempts, 'carrier operation.attempts'),
            last_error: carrier.last_error === null ? null : sellerString(carrier.last_error, 'carrier operation.last_error'),
          };
        })(),
      };
    }),
  };
}
export function SellerOrderDetailPage({ orderId }: { orderId: string }) {
  const [order, setOrder] = useState<Order | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');

  async function load() {
    setPending(true);
    setError('');
    try {
      const current = await sellerApiRequest(`/api/seller/orders/${orderId}`, { cache: 'no-store' }, decodeOrder);
      setOrder(current);
    } catch (cause) {
      setError(sellerErrorMessage(cause, 'Не удалось загрузить allocation'));
    } finally {
      setPending(false);
    }
  }

  useEffect(() => { void load(); }, [orderId]);

  const format = (amount: number, currency: string) => {
    const digits = new Intl.NumberFormat('ru-RU', { style: 'currency', currency }).resolvedOptions().maximumFractionDigits ?? 2;
    return new Intl.NumberFormat('ru-RU', { style: 'currency', currency }).format(amount / (10 ** digits));
  };

  return (
    <main className="seller-app" id="main-content">
      <SellerSidebar variant="orders" activePath="/orders" badge="B2B API" />
      <section className="seller-content seller-orders-content">
        <div className="private-bar"><span>SELLER / ORDER DETAIL</span><span>ALLOCATION SNAPSHOT</span></div>
        <p className="eyebrow">SELLER HUB / SE-13</p>
        <div className="page-heading"><h1>Allocation</h1><a className="seller-product-link" href="/orders">К заказам</a></div>
        {pending && <p className="seller-state" role="status">Загружаем снимок заказа…</p>}
        {error && <div className="seller-state seller-error" role="alert"><strong>{error}</strong><button className="seller-submit" type="button" onClick={() => void load()}>Повторить</button></div>}
        {order && !pending && <>
          <div className="seller-order-summary">
            <div><span>Идентификатор</span><strong>{order.id}</strong></div>
            <div><span>Распределён</span><strong>{new Date(order.allocated_at).toLocaleString('ru-RU')}</strong></div>
            <div><span>Состояние</span><strong>{order.status}</strong></div>
            <div><span>Сумма snapshot</span><strong>{format(order.total_minor, order.currency)}</strong></div>
          </div>
          <p className="seller-notice" role="status">Приёмка заказов, упаковка, отправка, возвраты, refund/restock и расчёты отключены до утверждения ADR. Показан только сохранённый снимок allocation; этот экран не подтверждает доставку или коммерческие обязательства.</p>
          {!!order.shipments.length && <div className="seller-table-wrap" tabIndex={0}><table className="seller-table seller-orders-table"><caption>Сохранённые тестовые записи посылок (только просмотр)</caption><thead><tr><th>Посылка</th><th>Сохранена</th><th>Статус</th><th>Позиции</th><th>Тестовая операция</th></tr></thead><tbody>{order.shipments.map((shipment) => <tr key={shipment.id}><th scope="row">{shipment.id.slice(0, 8).toUpperCase()}</th><td>{new Date(shipment.packed_at).toLocaleString('ru-RU')}</td><td>{shipment.status}</td><td>{shipment.lines.reduce((count, line) => count + line.quantity, 0)} шт.</td><td>{shipment.carrier_operation ? <><strong>{shipment.carrier_operation.tracking_number ?? shipment.carrier_operation.status}</strong><small className="seller-order-status-note">LOCAL TEST ONLY · не подтверждает реальную доставку</small></> : <span>Нет</span>}</td></tr>)}</tbody></table></div>}
          <div className="seller-table-wrap" tabIndex={0}><table className="seller-table seller-orders-table"><caption className="sr-only">Снимок товарных позиций allocation</caption><thead><tr><th>Товар</th><th>SKU</th><th>Количество</th><th>Цена строки</th></tr></thead><tbody>{order.items.map((item) => <tr key={item.id}><th scope="row">{item.product_title}</th><td>{item.sku_name}<small className="seller-order-id">{item.sku_id}</small></td><td>{item.quantity}</td><td>{format(item.line_total_minor, order.currency)}</td></tr>)}</tbody></table></div>
        </>}
      </section>
    </main>
  );
}
