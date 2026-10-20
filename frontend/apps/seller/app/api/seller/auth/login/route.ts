import { sellerProblem, sellerProblemResponse, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';

const cookieName = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';

const problem = (title: string, status: number, retryAfter?: string | null) => retryAfter
  ? sellerProblem(status, title, { headers: { 'Retry-After': retryAfter } })
  : sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  if (!base) return problem('Seller authentication is not configured', 503);
  const form = await request.formData().catch(() => null);
  const email = typeof form?.get('username') === 'string' ? String(form.get('username')).trim() : '';
  const password = typeof form?.get('password') === 'string' ? String(form.get('password')) : '';
  const sellerId = typeof form?.get('seller_id') === 'string' ? String(form.get('seller_id')) : '';
  if (!email || !password || email.length > 320 || password.length > 256) return problem('Invalid credentials', 400);
  if (sellerId && !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(sellerId)) return problem('Invalid organization selection', 400);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/login`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: email, password, ...(sellerId ? { seller_id: sellerId } : {}) }),
      cache: 'no-store',
    });
    if (!upstream.ok) {
      if (upstream.status === 401) return problem('Неверный email или пароль', 401);
      if (upstream.status === 409) {
        const payload = await upstream.json().catch(() => null) as { code?: string; organizations?: Array<{ id: string; company_name: string; role: string }>; detail?: { code?: string; organizations?: Array<{ id: string; company_name: string; role: string }> } } | null;
        const code = payload?.code || payload?.detail?.code;
        const organizations = payload?.organizations || payload?.detail?.organizations;
        if (code === 'ORGANIZATION_SELECTION_REQUIRED' && Array.isArray(organizations)) {
          return sellerProblemResponse(null, 409, 'Choose an organization to sign in', 'ORGANIZATION_SELECTION_REQUIRED', undefined, { extensions: { organizations } });
        }
        return problem('Organization selection is not valid for this account', 403);
      }
      if (upstream.status === 403) {
        const payload = await upstream.json().catch(() => null) as { message?: unknown; error?: { message?: unknown } } | null;
        const reason = typeof payload?.message === 'string' ? payload.message : payload?.error?.message;
        if (reason === 'Email verification required') return problem('Подтвердите email по ссылке из письма', 403);
        if (reason === 'Account is awaiting review') return problem('Аккаунт ожидает проверки данных магазина', 403);
        return problem('Вход в аккаунт временно недоступен', 403);
      }
      if (upstream.status === 429) {
        return problem('Too many attempts. Try again later', 429, upstream.headers.get('Retry-After') || '60');
      }
      return problem(upstream.status === 503 ? 'Вход временно недоступен' : 'Seller authentication failed', upstream.status === 503 ? 503 : 502);
    }
    const data = await upstream.json() as { access_token?: unknown; token_type?: unknown; expires_in?: unknown };
    if (typeof data.access_token !== 'string' || data.access_token.length < 20 || !Number.isInteger(data.expires_in) || Number(data.expires_in) < 1 || Number(data.expires_in) > 900) return problem('Seller authentication response is invalid', 502);
    const session = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/session`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${data.access_token}`,
        'X-Device-Label': 'Seller web browser',
      },
      cache: 'no-store',
    });
    if (!session.ok) return problem('Seller session could not be established', session.status === 401 ? 401 : 503);
    const sessionData = await session.json() as { access_token?: unknown; expires_in?: unknown };
    if (typeof sessionData.access_token !== 'string' || sessionData.access_token.length < 40 || !Number.isInteger(sessionData.expires_in) || Number(sessionData.expires_in) < 1 || Number(sessionData.expires_in) > 900) return problem('Seller session response is invalid', 502);
    const response = sellerJsonResponse(request, { ok: true }, { headers: { 'Cache-Control': 'no-store' } });
    response.cookies.set(cookieName, sessionData.access_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: Number(sessionData.expires_in) });
    return response;
  } catch {
    return problem('Seller authentication is unavailable', 503);
  }
}
