import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';

const problem = (title: string, status: number) => sellerProblem(status, title, { cacheControl: 'private, no-store' });
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const key = request.headers.get('Idempotency-Key');
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  const base = process.env.NEOMARKET_B2B_URL;
  if (!key || !uuid.test(key)) return problem('A valid Idempotency-Key is required', 400);
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);

  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/inventory/exports`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        'Idempotency-Key': key,
      },
      body: await request.text(),
      cache: 'no-store',
    });
    const body = await upstream.text();
    if (!upstream.ok) {
      return new NextResponse(body, {
        status: upstream.status,
        headers: {
          'Content-Type': upstream.headers.get('content-type') ?? 'application/json',
          'Cache-Control': 'private, no-store',
        },
      });
    }
    const result = JSON.parse(body) as { id?: string; download_token?: unknown };
    const downloadToken = result.download_token;
    delete result.download_token;
    if (typeof result.id === 'string' && typeof downloadToken === 'string') {
      const query = new URLSearchParams({ token: downloadToken });
      Object.assign(result, { download_url: `/api/seller/inventory/exports/${result.id}/download?${query}` });
    }
    return sellerJsonResponse(request, result, { status: upstream.status, headers: { 'Cache-Control': 'private, no-store' } });
  } catch {
    return problem('Inventory export is unavailable', 503);
  }
}
