import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';

const cookieName = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';
const problem = (title: string, status: number, retryAfter?: string | null) => retryAfter
  ? sellerProblem(status, title, { headers: { 'Retry-After': retryAfter } })
  : sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${cookieName}=([^;]+)`))?.[1];
  if (!base) return problem('Seller service is not configured', 503);
  if (!token) return problem('Seller authentication is required', 401);
  const body = await request.json().catch(() => null) as { email?: unknown; role?: unknown } | null;
  const email = typeof body?.email === 'string' ? body.email.trim() : '';
  const role = body?.role;
  const roles = ['MANAGER', 'CATALOG_EDITOR', 'WAREHOUSE_OPERATOR', 'SUPPORT', 'FINANCE', 'VIEWER'];
  if (!email || email.length > 320 || typeof role !== 'string' || !roles.includes(role)) {
    return problem('Укажите email и допустимую роль', 400);
  }
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/team/invitations`, {
      method: 'POST',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, role }),
      cache: 'no-store',
    });
    if (!upstream.ok) {
      const title = upstream.status === 409 ? 'Этот пользователь уже состоит в команде' : upstream.status === 429 ? 'Слишком много приглашений. Попробуйте позже' : upstream.status === 403 ? 'Приглашать сотрудников может только владелец' : upstream.status === 503 ? 'Не удалось отправить письмо-приглашение' : 'Не удалось создать приглашение';
      return problem(title, [400, 403, 409, 429, 503].includes(upstream.status) ? upstream.status : 502, upstream.status === 429 ? upstream.headers.get('Retry-After') : null);
    }
    const payload = await upstream.json();
    return sellerJsonResponse(request, payload, { status: 201, headers: { 'Cache-Control': 'no-store' } });
  } catch {
    return problem('Seller service is unavailable', 503);
  }
}
