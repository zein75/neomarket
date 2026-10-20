import { NextResponse } from 'next/server';

export function GET() {
  return NextResponse.json({ status: 'ok', service: 'seller' }, { headers: { 'Cache-Control': 'no-store' } });
}
