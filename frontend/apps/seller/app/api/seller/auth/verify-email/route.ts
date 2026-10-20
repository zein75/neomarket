import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';

const problem = (title: string, status: number) => sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  if (!base) return problem('Seller verification is not configured', 503);
  const body = await request.json().catch(() => null) as { token?: unknown } | null;
  const token = typeof body?.token === 'string' ? body.token : '';
  if (token.length < 32 || token.length > 128) return problem('Ссылка подтверждения некорректна', 400);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/verify-email`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
      cache: 'no-store',
    });
    if (!upstream.ok) {
      const title = upstream.status === 400 ? 'Ссылка истекла или уже использована' : 'Не удалось подтвердить email';
      return problem(title, upstream.status === 400 ? 400 : 503);
    }
    return sellerJsonResponse(request, 
      { status: 'PENDING_REVIEW', message: 'Email подтверждён. Аккаунт ожидает проверки.' },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  } catch {
    return problem('Сервис проверки временно недоступен', 503);
  }
}
