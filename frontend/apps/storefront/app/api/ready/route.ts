import { NextResponse } from 'next/server';

export async function GET() {
  const upstream = process.env.NEOMARKET_B2C_URL;
  if (!upstream) return NextResponse.json({ status: 'not_ready' }, { status: 503, headers: { 'cache-control': 'no-store' } });
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1000);
  try {
    const response = await fetch(`${upstream.replace(/\/$/, '')}/health`, { method: 'GET', cache: 'no-store', signal: controller.signal });
    if (!response.ok) return NextResponse.json({ status: 'not_ready' }, { status: 503, headers: { 'cache-control': 'no-store' } });
    return NextResponse.json({ status: 'ready' }, { headers: { 'cache-control': 'no-store' } });
  } catch {
    return NextResponse.json({ status: 'not_ready' }, { status: 503, headers: { 'cache-control': 'no-store' } });
  } finally { clearTimeout(timeout); }
}
