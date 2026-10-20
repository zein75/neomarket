import { NextResponse } from 'next/server';
import { csrfTokenFor, sellerCsrfCookie } from '../../../../../src/lib/csrf';
import { sellerProblem, sellerJsonResponse } from '../../../../../src/lib/seller-problem-details';

const accessCookie = process.env.NODE_ENV === 'production' ? '__Host-nm_seller_access' : 'nm_seller_access';

export async function GET(request: Request) {
  const token = csrfTokenFor(request);
  if (!token) return sellerProblem(503, 'Seller CSRF is unavailable');
  const response = sellerJsonResponse(request, { token }, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(sellerCsrfCookie, token, { httpOnly: false, sameSite: 'lax', secure: process.env.NODE_ENV === 'production', path: '/' });
  return response;
}
