import type { ProductCardDto } from '@neomarket/api-types';
import { useState } from 'react';
import styles from './ProductCard.module.css';

type ProductCardProps = {
  product: ProductCardDto;
  onAdd: (product: ProductCardDto) => void | Promise<void>;
  mutationsEnabled?: boolean;
  pending?: boolean;
  onFavorite?: (product: ProductCardDto) => void | Promise<void>;
  isFavorite?: boolean;
  favoritePending?: boolean;
};

function formatPrice(product: ProductCardDto) {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: product.currency,
    maximumFractionDigits: 0,
  }).format(product.priceMinor / 100);
}

/** Availability is server-owned and must be visible before a shopper can add an item. */
export function ProductCard({ product, onAdd, mutationsEnabled = true, pending = false, onFavorite, isFavorite = false, favoritePending = false }: ProductCardProps) {
  const [imageFailed, setImageFailed] = useState(false);
  const unavailable = product.availability !== 'available';
  const canAdd = !unavailable && !pending && mutationsEnabled;
  const stateLabel = unavailable ? 'Недоступно' : 'В наличии';
  const image = product.imageUrl && !imageFailed ? product.imageUrl : undefined;
  const productHref = `/product/${encodeURIComponent(product.id)}`;

  return (
    <article className={`product-card ${unavailable ? 'unavailable' : ''}`} data-product-id={product.id} data-state={unavailable ? product.availability : 'available'}>
      <a className="product-card-link" href={productHref} aria-label={`Открыть товар: ${product.title}`}>
        <div className="product-image">
          {image ? (
            <img src={image} alt={product.title} loading="lazy" decoding="async" onError={() => setImageFailed(true)} />
          ) : (
            <div className={styles.imageEmpty} role="img" aria-label={`Фото товара «${product.title}» не предоставлено`}>
              <span className={`material-symbols-outlined ${styles.imageEmptyIcon}`} aria-hidden="true">image_not_supported</span>
              <span className={styles.imageEmptyLabel}>Фото не предоставлено</span>
            </div>
          )}
          <span className="product-tag" aria-label={`Статус: ${stateLabel}`}>
            {unavailable ? 'UNAVAILABLE' : 'IN STOCK'}
          </span>
        </div>
      </a>
      {onFavorite && <button className={`product-favorite-button${isFavorite ? ' is-favorite' : ''}`} type="button" disabled={favoritePending} aria-busy={favoritePending} aria-pressed={isFavorite} aria-label={isFavorite ? `Удалить ${product.title} из избранного` : `Добавить ${product.title} в избранное`} onClick={() => { void onFavorite(product); }}><span className="material-symbols-outlined" aria-hidden="true">{isFavorite ? 'favorite' : 'favorite_border'}</span></button>}
      <div className="product-body">
        <div className="product-meta"><p className="eyebrow">{product.category}</p>{product.skuArticle && <span className="product-sku">АРТИКУЛ {product.skuArticle}</span>}</div>
        <h3><a className="product-title-link" href={productHref}>{product.title}</a></h3>
        {product.description && <p className="product-description">{product.description}</p>}
        {product.availableQuantity !== undefined && <p className="stock" aria-live="polite">{product.stockLabel}</p>}
        <div className="product-footer">
          <strong aria-label={`Цена: ${formatPrice(product)}`}>{formatPrice(product)}</strong>
          <button
            className="button button-primary product-cart-button"
            type="button"
            disabled={!canAdd}
            aria-label={unavailable ? `${product.title}: недоступно` : mutationsEnabled ? `Добавить ${product.title} в корзину` : `${product.title}: добавление через live API пока недоступно`}
            onClick={() => { void onAdd(product); }}
          >
            {unavailable ? 'Недоступно' : mutationsEnabled ? 'В корзину' : 'API не подключён'}
          </button>
        </div>
      </div>
    </article>
  );
}
