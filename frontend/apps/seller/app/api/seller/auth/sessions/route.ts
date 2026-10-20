import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../src/lib/seller-problem-details';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';

const problem = (title: string, status: number) => sellerProblem(status, title);

export async function GET(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/sessions`, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Seller sessions are unavailable', 503);
  }
}
