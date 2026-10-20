import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';

const cookieName = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';
const problem = (title: string, status: number) => sellerProblem(status, title);

export async function GET(request: Request) {
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${cookieName}=([^;]+)`))?.[1];
  if (!base) return problem('Seller service is not configured', 503);
  if (!token) return problem('Seller authentication is required', 401);
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/team/members`, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    const body = await upstream.json().catch(() => null);
    if (!upstream.ok) return problem('Не удалось загрузить участников команды', upstream.status);
    return sellerJsonResponse(request, body, { headers: { 'Cache-Control': 'no-store' } });
  } catch {
    return problem('Seller service is unavailable', 503);
  }
}
