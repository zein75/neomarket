import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';

const problem = (title: string, status: number) => sellerProblem(status, title);

export async function GET(request: Request, { params }: { params: Promise<{ orderId: string }> }) {
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);
  const { orderId } = await params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(orderId)) return problem('Seller order was not found', 404);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/orders/${orderId}`, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Seller order is unavailable', 503);
  }
}
