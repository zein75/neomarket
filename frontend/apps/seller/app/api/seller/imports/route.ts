import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../src/lib/trusted-origin';

const problem = (title: string, status: number) => sellerProblem(status, title);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const idempotencyKey = request.headers.get('Idempotency-Key');
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!idempotencyKey || !uuid.test(idempotencyKey)) return problem('A valid Idempotency-Key is required', 400);
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/inventory/imports`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'Idempotency-Key': idempotencyKey },
      body: await request.text(),
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Inventory import preview is unavailable', 503);
  }
}
