import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';

const problem = (title: string, status: number) => sellerProblem(status, title);

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const allowed = path.length === 1 && ['overview', 'transactions', 'settlements', 'payouts'].includes(path[0] ?? '');
  const statement = path.length === 2 && path[0] === 'statements' && typeof path[1] === 'string' && uuid.test(path[1]);
  if (!allowed && !statement) return problem('Finance route not found', 404);

  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!base) return problem('Seller service is not configured', 503);
  if (!token) return problem('Seller authentication is required', 401);

  const query = path[0] === 'overview' ? new URL(request.url).search : '';
  const url = `${base.replace(/\/$/, '')}/api/v1/seller/finance/${path.map(encodeURIComponent).join('/')}${query}`;
  try {
    const upstream = await sellerUpstreamFetch(request, url, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Seller finance service is unavailable', 503);
  }
}
