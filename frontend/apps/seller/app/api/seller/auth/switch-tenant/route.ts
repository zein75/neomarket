import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';

const cookieName = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';
const problem = (title: string, status: number) => sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${cookieName}=([^;]+)`))?.[1];
  if (!base) return problem('Seller service is not configured', 503);
  if (!token) return problem('Seller authentication is required', 401);
  const body = await request.json().catch(() => null) as { seller_id?: unknown } | null;
  if (typeof body?.seller_id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(body.seller_id)) {
    return problem('Choose a valid organization', 400);
  }
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/switch-tenant`, {
      method: 'POST',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ seller_id: body.seller_id }),
      cache: 'no-store',
    });
    if (!upstream.ok) return problem(upstream.status === 403 ? 'Your account does not have access to this organization' : 'Could not switch organization', upstream.status);
    const payload = await upstream.json() as { access_token?: unknown; expires_in?: unknown };
    if (typeof payload.access_token !== 'string' || !Number.isInteger(payload.expires_in) || Number(payload.expires_in) < 1 || Number(payload.expires_in) > 900) {
      return problem('Seller authentication response is invalid', 502);
    }
    const session = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/session`, {
      method: 'POST',
      headers: { Accept: 'application/json', Authorization: `Bearer ${payload.access_token}`, 'X-Device-Label': 'Seller web browser' },
      cache: 'no-store',
    });
    if (!session.ok) return problem('Seller session could not be renewed', session.status === 401 ? 401 : 503);
    const sessionPayload = await session.json() as { access_token?: unknown; expires_in?: unknown };
    if (typeof sessionPayload.access_token !== 'string' || sessionPayload.access_token.length < 40 || !Number.isInteger(sessionPayload.expires_in) || Number(sessionPayload.expires_in) < 1 || Number(sessionPayload.expires_in) > 900) {
      return problem('Seller session response is invalid', 502);
    }
    const response = sellerJsonResponse(request, { ok: true }, { headers: { 'Cache-Control': 'no-store' } });
    response.cookies.set(cookieName, sessionPayload.access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      path: '/',
      maxAge: Number(sessionPayload.expires_in),
    });
    return response;
  } catch {
    return problem('Seller service is unavailable', 503);
  }
}
