import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function POST(request: Request) {
const rid = requestId(request.headers.get('x-request-id')); const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1]; const csrf = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_csrf=([^;]+)/)?.[1]; const origin = request.headers.get('origin'); const expected = process.env.NEOMARKET_PUBLIC_ORIGIN;
  if ((origin && (!expected || origin !== expected.replace(/\/$/, ''))) || request.headers.get('sec-fetch-site') === 'cross-site' || !csrf || csrf !== request.headers.get('x-csrf-token')) return NextResponse.json({ type: 'about:blank', title: 'CSRF validation failed', status: 403, requestId: rid }, { status: 403 });
  const response = NextResponse.json({ authenticated: false }, { headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  response.cookies.set(process.env.NODE_ENV === 'production' ? '__Host-nm_access' : 'nm_access', '', { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 0 });
  response.cookies.set(process.env.NODE_ENV === 'production' ? '__Host-nm_refresh' : 'nm_refresh', '', { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 0 });
  if (!token || !process.env.NEOMARKET_B2C_URL) return response;
  try { await fetch(`${process.env.NEOMARKET_B2C_URL.replace(/\/$/, '')}/api/v1/auth/logout`, { method: 'POST', headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Request-ID': rid }, cache: 'no-store' }); } catch { /* local cookie is still revoked */ }
  return response;
}
