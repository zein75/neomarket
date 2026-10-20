/**
 * Allow the configured seller/public origin, plus the exact request origin in
 * non-production local development. The latter keeps local apps on their own
 * port usable without weakening cross-origin checks in production.
 */
export function isTrustedSellerOrigin(request: Request): boolean {
  const origin = request.headers.get('origin');
  const expected = (process.env.NEOMARKET_SELLER_ORIGIN ?? process.env.NEOMARKET_PUBLIC_ORIGIN)
    ?.replace(/\/$/, '');
  const localOrigin = new URL(request.url).origin;
  const requestHost = request.headers.get('host');
  let loopbackHostOrigin: string | undefined;
  if (process.env.NODE_ENV !== 'production' && requestHost) {
    try {
      const hostOrigin = new URL(`${new URL(request.url).protocol}//${requestHost}`);
      if (['localhost', '127.0.0.1', '[::1]', '::1'].includes(hostOrigin.hostname)) {
        loopbackHostOrigin = hostOrigin.origin;
      }
    } catch {
      loopbackHostOrigin = undefined;
    }
  }
  const trusted = !origin
    || (Boolean(expected) && origin === expected)
    || (process.env.NODE_ENV !== 'production' && (origin === localOrigin || origin === loopbackHostOrigin));

  return trusted && request.headers.get('sec-fetch-site') !== 'cross-site';
}
