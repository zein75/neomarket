import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../../src/lib/seller-problem-details';
import { csrfMatches } from '../../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../../src/lib/trusted-origin';

const cookieName = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';
const problem = (title: string, status: number) => sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${cookieName}=([^;]+)`))?.[1];
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller MFA provider is not configured', 501);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/mfa/challenge`, {
      method: 'POST',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      body: await request.text(),
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Seller MFA provider is unavailable', 503);
  }
}
