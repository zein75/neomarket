import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../../../src/lib/seller-problem-details';
import { isTrustedSellerOrigin } from '../../../../../../../src/lib/trusted-origin';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (title: string, status: number) => sellerProblem(status, title);

export async function GET(request: Request, { params }: { params: Promise<{ idempotencyKey: string }> }) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  const { idempotencyKey } = await params;
  if (!uuid.test(idempotencyKey)) return problem('Invalid draft operation key', 400);
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/seller/v1/products/drafts/${idempotencyKey}`, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Seller product draft recovery is unavailable', 503);
  }
}
