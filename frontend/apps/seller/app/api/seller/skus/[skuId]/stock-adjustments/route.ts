import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../../src/lib/trusted-origin';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (title: string, status: number) => sellerProblem(status, title);
export async function POST(request: Request, context: { params: Promise<{ skuId: string }> }) {
  const skuId = (await context.params).skuId; const base = process.env.NEOMARKET_B2B_URL; const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1]; const idempotencyKey = request.headers.get('idempotency-key');
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  if (!uuid.test(skuId) || !idempotencyKey || !uuid.test(idempotencyKey)) return problem('Valid SKU and Idempotency-Key are required', 400);
  if (!token) return problem('Seller authentication is required', 401); if (!base) return problem('Seller service is not configured', 503);
  const body = await request.json().catch(() => null) as { delta?: unknown; reason?: unknown } | null;
  if (!Number.isInteger(body?.delta) || body?.delta === 0 || typeof body?.reason !== 'string' || body.reason.trim().length < 3 || body.reason.length > 64) return problem('Delta and reason are required', 400);
  try { const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/skus/${skuId}/stock-adjustments`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ delta: body.delta, reason: body.reason.trim() }), cache: 'no-store' }); return await sellerUpstreamResponse(request, upstream); } catch { return problem('Stock adjustment is unavailable', 503); }
}
