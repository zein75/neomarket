import { NextResponse } from 'next/server';

export async function GET() {
  const token = crypto.randomUUID();
  const response = NextResponse.json({ token }, { headers: { 'cache-control': 'no-store' } });
  response.cookies.set('nm_csrf', token, { httpOnly: false, sameSite: 'lax', secure: process.env.NODE_ENV === 'production', path: '/' });
  return response;
}
