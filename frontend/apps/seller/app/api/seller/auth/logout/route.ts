import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';
import { sellerProblemResponse, sellerJsonResponse, sellerUpstreamFetch } from '../../../../../src/lib/seller-problem-details';

const cookieName = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return sellerProblemResponse(request, 403, 'Request origin is not trusted', 'UNTRUSTED_ORIGIN');
  if (!csrfMatches(request)) return sellerProblemResponse(request, 403, 'CSRF validation failed', 'CSRF_VALIDATION_FAILED');
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${cookieName}=([^;]+)`))?.[1];
  if (base && token) {
    try {
      const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/logout`, {
        method: 'POST',
        headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
        cache: 'no-store',
      });
      if (!upstream.ok && upstream.status !== 401) return sellerProblemResponse(request, upstream.status, 'Could not revoke seller session', 'SESSION_REVOCATION_FAILED');
    } catch {
      return sellerProblemResponse(request, 503, 'Seller session is unavailable', 'SESSION_REVOCATION_UNAVAILABLE');
    }
  }
  const response = sellerJsonResponse(request, { ok: true }, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(cookieName, '', { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 0 });
  return response;
}
