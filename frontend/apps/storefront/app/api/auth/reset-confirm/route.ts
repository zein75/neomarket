import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function POST(request: Request) {
  const rid = requestId(request.headers.get('x-request-id')); const base = process.env.NEOMARKET_B2C_URL; const body = await request.json().catch(() => null);
  const origin = request.headers.get('origin'); const expected = process.env.NEOMARKET_PUBLIC_ORIGIN;
  if ((origin && (!expected || origin !== expected.replace(/\/$/, ''))) || request.headers.get('sec-fetch-site') === 'cross-site') return NextResponse.json({ type: 'about:blank', title: 'Request origin is not trusted', status: 403, requestId: rid }, { status: 403 });
  if (!base || !body || typeof body !== 'object') return NextResponse.json({ type: 'about:blank', title: 'Invalid reset confirmation', status: base ? 400 : 503, requestId: rid }, { status: base ? 400 : 503 });
  const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/auth/reset-confirm`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Request-ID': rid }, body: JSON.stringify(body), cache: 'no-store' });
  return new NextResponse(null, { status: upstream.status, headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}
