import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

function problem(title: string, status: number, rid: string) {
  return NextResponse.json({ type: 'about:blank', title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}
function accessToken(request: Request) { return request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1]; }

export async function GET(request: Request) {
  const rid = requestId(request.headers.get('x-request-id')); const token = accessToken(request); const base = process.env.NEOMARKET_B2C_URL;
  if (!token) return problem('Buyer authentication is required', 401, rid);
  if (!base) return problem('Favorites service is not configured', 503, rid);
  const incoming = new URL(request.url); const query = new URLSearchParams();
  for (const name of ['limit', 'offset']) { const value = incoming.searchParams.get(name); if (value && /^\d{1,5}$/.test(value)) query.set(name, value); }
  const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/favorites?${query}`, { headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Request-ID': rid }, cache: 'no-store' });
  return new NextResponse(await response.text(), { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}
