import { NextResponse } from 'next/server';
import * as oidc from 'openid-client';
import { oidcConfiguration, oidcCookieName, publicOrigin, requiredMfaClaims, secureCookies } from '../../../../src/oidc';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const config = await oidcConfiguration();
    const origin = publicOrigin();
    const { acr } = requiredMfaClaims();
    const codeVerifier = oidc.randomPKCECodeVerifier();
    const codeChallenge = await oidc.calculatePKCECodeChallenge(codeVerifier);
    const state = oidc.randomState();
    const nonce = oidc.randomNonce();
    const claims = acr ? JSON.stringify({ id_token: { acr: { essential: true, values: [acr] } } }) : undefined;
    const authUrl = oidc.buildAuthorizationUrl(config, {
      client_id: process.env.ADMIN_OIDC_CLIENT_ID!,
      redirect_uri: `${origin}/api/auth/callback`,
      response_type: 'code',
      scope: 'openid profile email',
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
      state,
      nonce,
      prompt: 'login',
      max_age: '0',
      ...(claims ? { claims } : {}),
    });
    const response = NextResponse.redirect(authUrl);
    for (const [key, value] of Object.entries({ state, nonce, verifier: codeVerifier, flow: 'login', returnTo: '/' })) {
      response.cookies.set(oidcCookieName(key as 'state' | 'nonce' | 'verifier'), value, {
        httpOnly: true,
        secure: secureCookies(),
        sameSite: 'lax',
        path: '/',
        maxAge: 600,
      });
    }
    response.headers.set('Cache-Control', 'no-store');
    return response;
  } catch (error) {
    console.error('Admin OIDC login initialization failed', error instanceof Error ? error.message : String(error));
    return NextResponse.json({ error: 'Admin OIDC is not configured' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}
