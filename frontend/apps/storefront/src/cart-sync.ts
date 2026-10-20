const CART_SYNC_KEY = 'neomarket.cart.changed';

/** Notify other same-origin tabs that they must re-read the authoritative cart. */
export function announceCartChanged(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(CART_SYNC_KEY, `${Date.now()}:${Math.random()}`);
  } catch {
    // A focused/visible tab also refreshes on focus, so storage-disabled
    // environments still converge without persisting any cart data locally.
  }
}

export function isCartSyncEvent(event: StorageEvent): boolean {
  return event.key === CART_SYNC_KEY;
}
