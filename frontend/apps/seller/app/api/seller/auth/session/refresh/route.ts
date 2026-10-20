import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../../src/lib/seller-problem-details';
import { isTrustedSellerOrigin } from '../../../../../../src/lib/trusted-origin';
import { csrfMatches } from '../../../../../../src/lib/csrf';

const problem = (title: string, status: number) => sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/session/refresh`, {
      method: 'POST',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Device-Label': 'Seller web browser' },
      cache: 'no-store',
    });
    if (!upstream.ok) return problem('Seller session refresh failed', upstream.status);
    const body = await upstream.text();
    const payload = JSON.parse(body) as { access_token?: unknown; expires_in?: unknown };
    if (!payload || typeof payload.access_token !== 'string' || !Number.isInteger(payload.expires_in) || Number(payload.expires_in) < 1 || Number(payload.expires_in) > 900) return problem('Seller session response is invalid', 502);
    const response = await sellerUpstreamResponse(request, new Response(body, { status: upstream.status, headers: upstream.headers }));
    response.cookies.set(process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access', payload.access_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: Number(payload.expires_in) });
    return response;
  } catch {
    return problem('Seller session service is unavailable', 503);
  }
}
