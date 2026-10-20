import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';

const problem = (title: string, status: number, retryAfter?: string | null) => retryAfter
  ? sellerProblem(status, title, { headers: { 'Retry-After': retryAfter } })
  : sellerProblem(status, title);

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  const base = process.env.NEOMARKET_B2B_URL;
  if (!base) return problem('Seller registration is not configured', 503);
  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  const email = typeof body?.email === 'string' ? body.email.trim() : '';
  const password = typeof body?.password === 'string' ? body.password : '';
  const companyName = typeof body?.company_name === 'string' ? body.company_name.trim() : '';
  if (!email || email.length > 320 || password.length < 12 || password.length > 256 || !companyName || companyName.length > 255) {
    return problem('Проверьте email, пароль и название компании', 400);
  }
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/auth/register`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, company_name: companyName }),
      cache: 'no-store',
    });
    if (!upstream.ok) {
      const title = upstream.status === 409
        ? 'Аккаунт с таким email уже существует'
        : upstream.status === 429
          ? 'Слишком много попыток. Попробуйте позже'
          : upstream.status === 503
            ? 'Сейчас не удаётся отправить письмо подтверждения'
            : 'Не удалось создать аккаунт';
      return problem(title, [400, 409, 429, 503].includes(upstream.status) ? upstream.status : 502, upstream.status === 429 ? upstream.headers.get('Retry-After') : null);
    }
    return sellerJsonResponse(request, 
      { status: 'PENDING_EMAIL', message: 'Проверьте почту: ссылка для подтверждения действует 30 минут.' },
      { status: 202, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch {
    return problem('Сервис регистрации временно недоступен', 503);
  }
}
