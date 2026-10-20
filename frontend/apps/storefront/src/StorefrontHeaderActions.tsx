'use client';

type StorefrontHeaderActionsProps = {
  favoriteCount: number | null;
  cartCount: number | null;
};

export function StorefrontHeaderActions({ favoriteCount, cartCount }: StorefrontHeaderActionsProps) {
  const favoriteLabel = favoriteCount === null ? 'Избранное' : `Избранное, ${favoriteCount} товаров`;
  const cartLabel = cartCount === null ? 'Корзина' : `Корзина, ${cartCount} товаров`;

  return <div className="storefront-header-actions">
    <a className="storefront-header-action" href="/favorites" aria-label={favoriteLabel}>
      <span className="material-symbols-outlined" aria-hidden="true">{favoriteCount ? 'favorite' : 'favorite_border'}</span>
      {favoriteCount !== null && favoriteCount > 0 && <span className="storefront-header-count" aria-live="polite">{favoriteCount}</span>}
    </a>
    <a className="storefront-header-action" href="/cart" aria-label={cartLabel}>
      <span className="material-symbols-outlined" aria-hidden="true">shopping_bag</span>
      {cartCount !== null && cartCount > 0 && <span className="storefront-header-count" aria-live="polite">{cartCount}</span>}
    </a>
  </div>;
}
