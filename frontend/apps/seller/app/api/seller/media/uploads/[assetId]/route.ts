import {
  isSellerUpstreamTimeout,
  sellerProblemResponse,
  sellerUpstreamFetch,
  sellerUpstreamResponse,
} from '../../../../../../src/lib/seller-problem-details';
import { isTrustedSellerOrigin } from '../../../../../../src/lib/trusted-origin';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (request: Request, title: string, status: number, code: string) =>
  sellerProblemResponse(request, status, title, code);

export async function PUT(request: Request, context: { params: Promise<{ assetId: string }> }) {
  if (!isTrustedSellerOrigin(request)) return problem(request, 'Request origin is not trusted', 403, 'ACCESS_DENIED');
  const { assetId } = await context.params;
  if (!uuid.test(assetId)) return problem(request, 'Invalid media id', 400, 'INVALID_REQUEST');
  const url = new URL(request.url);
  const signed = url.searchParams.get('token');
  const base = process.env.NEOMARKET_B2B_URL;
  if (!signed || !base) return problem(request, 'Signed media upload is unavailable', 503, 'DEPENDENCY_UNAVAILABLE');
  const length = Number(request.headers.get('content-length') ?? 0);
  if (!Number.isFinite(length) || length < 1 || length > 10_000_000) return problem(request, 'Image exceeds the 10 MB limit', 413, 'PAYLOAD_TOO_LARGE');
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/media/uploads/${assetId}?token=${encodeURIComponent(signed)}`, {
      method: 'PUT',
      headers: { 'Content-Type': request.headers.get('content-type') ?? 'application/octet-stream', 'Content-Length': String(length) },
      body: await request.arrayBuffer(),
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem(request, 'Image upload result is unknown; check its status before retrying', 504, 'WRITE_RESULT_UNKNOWN');
  }
}

export async function GET(request: Request, context: { params: Promise<{ assetId: string }> }) {
  if (!isTrustedSellerOrigin(request)) return problem(request, 'Request origin is not trusted', 403, 'ACCESS_DENIED');
  const { assetId } = await context.params;
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!uuid.test(assetId)) return problem(request, 'Invalid media id', 400, 'INVALID_REQUEST');
  if (!token || !base) return problem(request, 'Seller authentication is required', 401, 'AUTHENTICATION_REQUIRED');
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/media/uploads/${assetId}`, { headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }, cache: 'no-store' });
    return await sellerUpstreamResponse(request, upstream);
  } catch (error) {
    return isSellerUpstreamTimeout(error)
      ? problem(request, 'Media status timed out', 504, 'UPSTREAM_TIMEOUT')
      : problem(request, 'Media status is unavailable', 503, 'DEPENDENCY_UNAVAILABLE');
  }
}
