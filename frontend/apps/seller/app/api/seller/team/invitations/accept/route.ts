import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../../src/lib/trusted-origin';

const problem = (title: string, status: number, retryAfter?: string | null) => retryAfter
  ? sellerProblem(status, title, { headers: { 'Retry-After': retryAfter } })
  : sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  if (!base) return problem('Seller service is not configured', 503);
  const body = await request.json().catch(() => null) as { email?: unknown; password?: unknown; token?: unknown } | null;
  const email = typeof body?.email === 'string' ? body.email.trim() : '';
  const password = typeof body?.password === 'string' ? body.password : '';
  const token = typeof body?.token === 'string' ? body.token : '';
  if (!email || email.length > 320 || password.length < 12 || password.length > 256 || token.length < 32 || token.length > 128) {
    return problem('Проверьте email, пароль и ссылку-приглашение', 400);
  }
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/team/invitations/accept`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, token }),
      cache: 'no-store',
    });
    if (!upstream.ok) {
      const title = upstream.status === 400 ? 'Приглашение истекло или уже использовано' : upstream.status === 401 ? 'Неверный email или пароль' : upstream.status === 429 ? 'Слишком много попыток. Попробуйте позже' : 'Не удалось принять приглашение';
      return problem(title, [400, 401, 429].includes(upstream.status) ? upstream.status : 502, upstream.status === 429 ? upstream.headers.get('Retry-After') : null);
    }
    return sellerJsonResponse(request, await upstream.json(), { status: 201, headers: { 'Cache-Control': 'no-store' } });
  } catch {
    return problem('Seller service is unavailable', 503);
  }
}
