'use client';

import type { ProductCardDto } from '@neomarket/api-types';
import { QuantityStepper } from '@neomarket/ui';

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 });

type CartViewProps = {
  lines: ProductCardDto[];
  cart: Record<string, number>;
  totalMinor: number;
  cartValid: boolean;
  pending: boolean;
  onRemove: (id: string) => void;
  onQuantity: (id: string, quantity: number) => void;
  onClear: () => void;
  onCheckout: () => void;
  maxQuantity?: (id: string) => number;
};

export function CartView({ lines, cart, totalMinor, cartValid, pending, onRemove, onQuantity, onClear, onCheckout, maxQuantity }: CartViewProps) {
  const unitCount = Object.values(cart).reduce((sum, quantity) => sum + quantity, 0);

  return <section className="cart-page" aria-label="Корзина">
    <section className="cart-progress" aria-label="Прогресс оформления заказа">
      <div className="cart-progress-ref"><span aria-hidden="true" />CHECKOUT FLOW / CART</div>
      <nav aria-label="Этапы оформления">
        <ol>
          <li aria-current="step"><span>01.</span> Корзина <b aria-hidden="true">✓</b></li>
          <li><span>02.</span> Адрес доставки</li>
          <li><span>03.</span> Получение</li>
          <li><span>04.</span> Оплата</li>
          <li><span>05.</span> Подтверждение</li>
        </ol>
      </nav>
    </section>

    <div className="cart-layout">
      <section className="cart-main" aria-labelledby="cart-heading">
        <div className="cart-page-heading">
          <div>
            <p className="eyebrow">SF-06 / CART</p>
            <h1 id="cart-heading">Корзина</h1>
            <p className="section-copy">Состав и сумма обновляются по ответу сервера. Недоступные товары не включаются в итог.</p>
          </div>
          {lines.length > 0 && <button className="cart-clear-button" type="button" disabled={pending} onClick={onClear}>Очистить корзину</button>}
        </div>

        {!cartValid && <div className="cart-validation-warning" role="alert"><strong>Корзина требует проверки</strong><span>Цена, наличие или количество изменились. Обновите данные с сервера перед оформлением.</span></div>}

        {lines.length === 0 ? <div className="cart-empty-panel">
          <p className="eyebrow">[ 0 ПОЗИЦИЙ ]</p>
          <h2>Корзина пуста</h2>
          <p>Добавьте доступный товар из каталога, чтобы начать заказ.</p>
          <a className="button button-primary" href="/catalog">Открыть каталог</a>
        </div> : <section className="cart-items" aria-labelledby="cart-items-heading">
          <div className="cart-items-heading">
            <div><h2 id="cart-items-heading">Позиции корзины</h2><span>{lines.length} поз. / {unitCount} ед.</span></div>
            <small>СЕРВЕРНАЯ КОРЗИНА</small>
          </div>
          <div className="cart-item-list" aria-busy={pending}>
            {lines.map((line) => {
              const quantity = cart[line.id] ?? 0;
              const available = line.availability === 'available';
              return <article className={`cart-item${available ? '' : ' is-unavailable'}`} key={line.id}>
                <div className="cart-item-media">
                  {line.imageUrl ? <img src={line.imageUrl} alt={line.title} /> : <div role="img" aria-label={`Изображение товара «${line.title}» не предоставлено`}>Изображение<br />не предоставлено</div>}
                  <span>{available ? 'В НАЛИЧИИ' : 'НЕДОСТУПЕН'}</span>
                </div>
                <div className="cart-item-main">
                  <div className="cart-item-meta"><span>{line.category}</span><span>{available ? line.stockLabel : 'Позиция не входит в сумму'}</span></div>
                  <h3>{line.title}</h3>
                  <span className="cart-item-quantity-label">Количество: {available ? quantity : '—'}</span>
                  <div className="cart-item-controls">
                    {available && <QuantityStepper value={quantity} min={1} max={maxQuantity?.(line.id) ?? 99} disabled={pending} label={`Количество: ${line.title}`} onChange={(next) => onQuantity(line.id, next)} />}
                    <strong className={available ? '' : 'muted'}>{available ? money.format((line.priceMinor * quantity) / 100) : '—'}</strong>
                  </div>
                </div>
                <button className="cart-remove-button" type="button" title="Удалить товар" disabled={pending} aria-label={`Удалить ${line.title}`} onClick={() => onRemove(line.id)}>
                  <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M7 8v11h10V8M9 8V5h6v3M5 8h14M10 11v5M14 11v5" /></svg>
                </button>
              </article>;
            })}
          </div>
        </section>}
      </section>

      <aside className="cart-summary" aria-labelledby="cart-summary-heading">
        <div className="cart-summary-header"><h2 id="cart-summary-heading">Итог заказа</h2><span>СЕРВЕРНЫЙ РАСЧЁТ</span></div>
        <div className="cart-summary-rows">
          <div className="cart-summary-row"><span>Товары ({lines.length} поз. / {unitCount} ед.)</span><strong>{money.format(totalMinor / 100)}</strong></div>
          <div className="cart-summary-row is-muted"><span>Доставка</span><span>Не подтверждена</span></div>
        </div>
        <div className="cart-summary-total"><span>К оплате за товары</span><strong>{money.format(totalMinor / 100)}</strong></div>
        <p className="cart-summary-note">Стоимость доставки и окончательные условия будут показаны только после подтверждения сервером.</p>
        <button className="button button-primary wide cart-checkout-button" disabled={!totalMinor || pending || !cartValid} onClick={onCheckout}>Перейти к оформлению <span aria-hidden="true">→</span></button>
      </aside>
    </div>
  </section>;
}
