import { createHmac, timingSafeEqual } from 'node:crypto';

const accessCookie = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';
const csrfCookie = 'nm_seller_csrf';

function cookie(request: Request, name: string) {
  return request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))?.[1] ?? '';
}

export function csrfTokenFor(request: Request) {
  const access = cookie(request, accessCookie);
  const secret = process.env.NEOMARKET_CSRF_SECRET || process.env.B2B_SECRET_KEY;
  if (!secret) return null;
  return createHmac('sha256', secret).update(access || 'seller-anonymous-session').digest('hex');
}

export function csrfMatches(request: Request) {
  const supplied = request.headers.get('x-csrf-token') ?? '';
  const stored = cookie(request, csrfCookie);
  const access = cookie(request, accessCookie);
  const secret = process.env.NEOMARKET_CSRF_SECRET || process.env.B2B_SECRET_KEY;
  if (!supplied || !stored || !secret || supplied !== stored) return false;
  const expected = createHmac('sha256', secret).update(access || 'seller-anonymous-session').digest();
  const actual = Buffer.from(supplied, 'hex');
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export const sellerCsrfCookie = csrfCookie;
