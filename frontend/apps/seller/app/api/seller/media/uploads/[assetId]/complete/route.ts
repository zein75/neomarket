import {
  sellerProblemResponse,
  sellerUpstreamFetch,
  sellerUpstreamResponse,
} from '../../../../../../../src/lib/seller-problem-details';
import { csrfMatches } from '../../../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../../../src/lib/trusted-origin';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (request: Request, title: string, status: number, code: string) =>
  sellerProblemResponse(request, status, title, code);

export async function POST(request: Request, context: { params: Promise<{ assetId: string }> }) {
  if (!isTrustedSellerOrigin(request)) return problem(request, 'Request origin is not trusted', 403, 'ACCESS_DENIED');
  if (!csrfMatches(request)) return problem(request, 'CSRF validation failed', 403, 'CSRF_VALIDATION_FAILED');
  const { assetId } = await context.params;
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!uuid.test(assetId)) return problem(request, 'Invalid media id', 400, 'INVALID_REQUEST');
  if (!token || !base) return problem(request, 'Seller authentication is required', 401, 'AUTHENTICATION_REQUIRED');
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/media/uploads/${assetId}/complete`, { method: 'POST', headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }, cache: 'no-store' });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem(request, 'Media completion result is unknown; check its status before retrying', 504, 'WRITE_RESULT_UNKNOWN');
  }
}
