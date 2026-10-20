import {
  isSellerUpstreamTimeout,
  sellerProblemResponse,
  sellerUpstreamFetch,
  sellerUpstreamResponse,
} from '../../../../../src/lib/seller-problem-details';

export async function GET(request: Request) {
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return sellerProblemResponse(request, 401, 'Seller authentication is required', 'AUTHENTICATION_REQUIRED');
  if (!base) return sellerProblemResponse(request, 503, 'Seller service is not configured', 'DEPENDENCY_NOT_CONFIGURED');
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/dashboard/metrics`, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    return sellerUpstreamResponse(request, upstream);
  } catch (error) {
    return isSellerUpstreamTimeout(error)
      ? sellerProblemResponse(request, 504, 'Seller dashboard metrics timed out', 'UPSTREAM_TIMEOUT')
      : sellerProblemResponse(request, 503, 'Seller dashboard metrics are unavailable', 'DEPENDENCY_UNAVAILABLE');
  }
}
