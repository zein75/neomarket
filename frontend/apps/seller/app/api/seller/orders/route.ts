import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';

const problem = (title: string, status: number) => sellerProblem(status, title);

export async function GET(request: Request) {
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);

  const incoming = new URL(request.url);
  const limit = Math.max(1, Math.min(100, Number(incoming.searchParams.get('limit')) || 50));
  const cursor = incoming.searchParams.get('cursor');
  if (cursor && cursor.length > 1024) return problem('Seller order cursor is invalid', 422);
  try {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set('cursor', cursor);
    const upstream = await sellerUpstreamFetch(request, 
      `${base.replace(/\/$/, '')}/api/v1/seller/orders?${query}`,
      { headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }, cache: 'no-store' },
    );
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Seller orders are unavailable', 503);
  }
}
