import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';
import { csrfMatches } from '../../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../../src/lib/trusted-origin';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (title: string, status: number) => sellerProblem(status, title);

async function mutate(request: Request, context: { params: Promise<{ userId: string }> }, method: 'PATCH' | 'DELETE') {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const userId = (await context.params).userId;
  if (!uuid.test(userId)) return problem('Invalid member id', 400);
  const revision = request.headers.get('If-Match');
  if (!revision) return problem('If-Match revision is required', 428);
  const base = process.env.NEOMARKET_B2B_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);

  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/team/members/${userId}`, {
      method,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'If-Match': revision,
      },
      body: await request.text(),
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Seller team service is unavailable', 503);
  }
}

export async function PATCH(request: Request, context: { params: Promise<{ userId: string }> }) {
  return mutate(request, context, 'PATCH');
}

export async function DELETE(request: Request, context: { params: Promise<{ userId: string }> }) {
  return mutate(request, context, 'DELETE');
}
