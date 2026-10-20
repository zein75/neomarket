import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../src/lib/trusted-origin';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (title: string, status: number) => sellerProblem(status, title);

export async function GET(request: Request, context: { params: Promise<{ productId: string }> }) {
  const productId = (await context.params).productId; const base = process.env.NEOMARKET_B2B_URL; const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!uuid.test(productId)) return problem('Invalid product id', 400); if (!token) return problem('Seller authentication is required', 401); if (!base) return problem('Seller service is not configured', 503);
  try { const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/products/${productId}`, { headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }, cache: 'no-store' }); return await sellerUpstreamResponse(request, upstream); } catch { return problem('Seller product is unavailable', 503); }
}

export async function PUT(request: Request, context: { params: Promise<{ productId: string }> }) {
  const productId = (await context.params).productId; const base = process.env.NEOMARKET_B2B_URL; const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1]; const revision = request.headers.get('If-Match');
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403); if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  if (!uuid.test(productId)) return problem('Invalid product id', 400); if (!revision) return problem('If-Match revision is required', 428); if (!token) return problem('Seller authentication is required', 401); if (!base) return problem('Seller service is not configured', 503);
  try { const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/products/${productId}`, { method: 'PUT', headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'If-Match': revision }, body: await request.text(), cache: 'no-store' }); return await sellerUpstreamResponse(request, upstream); } catch { return problem('Seller product update is unavailable', 503); }
}

export async function PATCH(request: Request, context: { params: Promise<{ productId: string }> }) {
  const productId = (await context.params).productId; const base = process.env.NEOMARKET_B2B_URL; const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1]; const revision = request.headers.get('If-Match');
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403); if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  if (!uuid.test(productId)) return problem('Invalid product id', 400); if (!revision) return problem('If-Match revision is required', 428); if (!token) return problem('Seller authentication is required', 401); if (!base) return problem('Seller service is not configured', 503);
  try { const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/products/${productId}`, { method: 'PATCH', headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'If-Match': revision }, body: await request.text(), cache: 'no-store' }); return await sellerUpstreamResponse(request, upstream); } catch { return problem('Seller draft is unavailable', 503); }
}

export async function DELETE(request: Request, context: { params: Promise<{ productId: string }> }) {
  const productId = (await context.params).productId; const base = process.env.NEOMARKET_B2B_URL; const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403); if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  if (!uuid.test(productId)) return problem('Invalid product id', 400); if (!token) return problem('Seller authentication is required', 401); if (!base) return problem('Seller service is not configured', 503);
  try { const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/products/${productId}`, { method: 'DELETE', headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }, cache: 'no-store' }); return await sellerUpstreamResponse(request, upstream); } catch { return problem('Seller product deletion is unavailable', 503); }
}
