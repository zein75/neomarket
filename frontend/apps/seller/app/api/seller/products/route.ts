import { csrfMatches } from '../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../src/lib/trusted-origin';
import {
  isSellerUpstreamTimeout,
  sellerProblemResponse,
  sellerUpstreamFetch,
  sellerUpstreamResponse,
} from '../../../../src/lib/seller-problem-details';

const problem = (request: Request, title: string, status: number, code: string) =>
  sellerProblemResponse(request, status, title, code);

export async function GET(request: Request) {
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return problem(request, 'Seller authentication is required', 401, 'AUTHENTICATION_REQUIRED');
  if (!base) return problem(request, 'Seller service is not configured', 503, 'DEPENDENCY_NOT_CONFIGURED');

  const incoming = new URL(request.url);
  const includeSkus = incoming.searchParams.get('include_skus') === 'true';
  const limit = incoming.searchParams.get('limit') || '100';
  const search = incoming.searchParams.get('search');
  const initialCursor = incoming.searchParams.get('cursor') || '';

  try {
    const loadPage = async (cursor: string) => {
      const query = new URLSearchParams({ limit, include_skus: String(includeSkus) });
      if (cursor) query.set('cursor', cursor);
      if (search && search.length <= 1024) query.set('search', search);
      const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/products?${query}`, {
        headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
        cache: 'no-store',
      });
      return upstream;
    };

    const upstream = await loadPage(initialCursor);
    return sellerUpstreamResponse(request, upstream);
  } catch (error) {
    return isSellerUpstreamTimeout(error)
      ? problem(request, 'Seller products request timed out', 504, 'UPSTREAM_TIMEOUT')
      : problem(request, 'Seller products are unavailable', 503, 'DEPENDENCY_UNAVAILABLE');
  }
}

export async function POST(request: Request) {
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!isTrustedSellerOrigin(request)) return problem(request, 'Request origin is not trusted', 403, 'UNTRUSTED_ORIGIN');
  if (!csrfMatches(request)) return problem(request, 'CSRF validation failed', 403, 'CSRF_VALIDATION_FAILED');
  if (!token) return problem(request, 'Seller authentication is required', 401, 'AUTHENTICATION_REQUIRED');
  if (!base) return problem(request, 'Seller service is not configured', 503, 'DEPENDENCY_NOT_CONFIGURED');
  try {
    const body = await request.text();
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/products`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body, cache: 'no-store' });
    return sellerUpstreamResponse(request, upstream);
  } catch (error) {
    return isSellerUpstreamTimeout(error)
      ? problem(request, 'Seller product creation timed out; check its status before retrying', 504, 'WRITE_RESULT_UNKNOWN')
      : problem(request, 'Seller product creation is unavailable', 503, 'DEPENDENCY_UNAVAILABLE');
  }
}
