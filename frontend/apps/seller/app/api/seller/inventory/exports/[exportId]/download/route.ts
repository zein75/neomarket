import {
  isSellerUpstreamTimeout,
  sellerProblemResponse,
  sellerStreamingResponse,
  sellerStreamingUpstreamFetch,
} from '../../../../../../../src/lib/seller-problem-details';

const problem = (request: Request, title: string, status: number, code?: string) =>
  sellerProblemResponse(request, status, title, code ?? (status === 401 ? 'AUTHENTICATION_REQUIRED' : status === 403 ? 'ACCESS_DENIED' : status === 404 ? 'NOT_FOUND' : 'SELLER_REQUEST_FAILED'), undefined, {
    cacheControl: 'private, no-store',
    headers: { 'X-Content-Type-Options': 'nosniff' },
  });
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(request: Request, context: { params: Promise<{ exportId: string }> }) {
  const { exportId } = await context.params;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  const signedToken = new URL(request.url).searchParams.get('token');
  const base = process.env.NEOMARKET_B2B_URL;
  if (!uuid.test(exportId)) return problem(request, 'Inventory export was not found', 404);
  if (!token) return problem(request, 'Seller authentication is required', 401);
  if (!signedToken || signedToken.length > 1024) return problem(request, 'Inventory export link is invalid', 403);
  if (!base) return problem(request, 'Seller service is not configured', 503);

  try {
    const upstream = await sellerStreamingUpstreamFetch(request,
      `${base.replace(/\/$/, '')}/api/v1/seller/inventory/exports/${exportId}/download?${new URLSearchParams({ token: signedToken })}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' },
    );
    return await sellerStreamingResponse(request, upstream, {
      cacheControl: 'private, no-store',
      headers: { 'X-Content-Type-Options': 'nosniff' },
    });
  } catch (error) {
    return isSellerUpstreamTimeout(error)
      ? problem(request, 'Inventory export download timed out', 504, 'UPSTREAM_TIMEOUT')
      : problem(request, 'Inventory export download is unavailable', 503, 'DEPENDENCY_UNAVAILABLE');
  }
}
