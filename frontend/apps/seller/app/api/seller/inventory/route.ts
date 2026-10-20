import {
  isSellerUpstreamTimeout,
  sellerProblemResponse,
  sellerUpstreamFetch,
  sellerUpstreamResponse,
} from '../../../../src/lib/seller-problem-details';

export async function GET(request: Request) {
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return sellerProblemResponse(request, 401, 'Seller authentication is required', 'AUTHENTICATION_REQUIRED');
  if (!base) return sellerProblemResponse(request, 503, 'Seller service is not configured', 'DEPENDENCY_NOT_CONFIGURED');

  const incoming = new URL(request.url);
  const requestedLimit = Number(incoming.searchParams.get('limit')) || 50;
  const limit = Math.max(1, Math.min(100, requestedLimit));
  const cursor = incoming.searchParams.get('cursor');
  const queryText = incoming.searchParams.get('query')?.trim();
  const status = incoming.searchParams.get('status');
  if (cursor && cursor.length > 1024) return sellerProblemResponse(request, 422, 'Seller inventory cursor is invalid', 'INVALID_CURSOR');
  if (queryText && queryText.length > 120) return sellerProblemResponse(request, 422, 'Seller inventory query is too long', 'QUERY_TOO_LONG');
  if (status && !['available', 'reserved', 'unavailable', 'inactive'].includes(status)) {
    return sellerProblemResponse(request, 422, 'Seller inventory status is invalid', 'INVALID_STATUS');
  }

  try {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set('cursor', cursor);
    if (queryText) query.set('query', queryText);
    if (status) query.set('status', status);
    const upstream = await sellerUpstreamFetch(request,
      `${base.replace(/\/$/, '')}/api/v1/seller/inventory?${query}`,
      { headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }, cache: 'no-store' },
    );
    return sellerUpstreamResponse(request, upstream);
  } catch (error) {
    return isSellerUpstreamTimeout(error)
      ? sellerProblemResponse(request, 504, 'Seller inventory request timed out', 'UPSTREAM_TIMEOUT')
      : sellerProblemResponse(request, 503, 'Seller inventory is unavailable', 'DEPENDENCY_UNAVAILABLE');
  }
}
