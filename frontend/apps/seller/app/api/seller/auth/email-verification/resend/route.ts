import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { isTrustedSellerOrigin } from '../../../../../../src/lib/trusted-origin';

const problem = (title: string, status: number, retryAfter?: string | null) => retryAfter
  ? sellerProblem(status, title, { headers: { 'Retry-After': retryAfter } })
  : sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  if (!base) return problem('Seller registration is not configured', 503);
  const body = await request.json().catch(() => null) as { email?: unknown } | null;
  const email = typeof body?.email === 'string' ? body.email.trim() : '';
  if (!email || email.length > 320) return problem('Введите корректный email', 400);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/email-verification/resend`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
      cache: 'no-store',
    });
    if (!upstream.ok) {
      const title = upstream.status === 429 ? 'Слишком много попыток. Попробуйте позже' : 'Не удалось отправить письмо';
      return problem(title, upstream.status === 429 ? 429 : 503, upstream.status === 429 ? upstream.headers.get('Retry-After') : null);
    }
    return sellerJsonResponse(request, 
      { message: 'Если аккаунту нужно подтверждение, мы отправили новую ссылку.' },
      { status: 202, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch {
    return problem('Сервис регистрации временно недоступен', 503);
  }
}
