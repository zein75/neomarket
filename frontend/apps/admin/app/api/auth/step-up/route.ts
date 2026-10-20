import { NextResponse, type NextRequest } from 'next/server';
import * as oidc from 'openid-client';
import {
  apiUrl,
  oidcConfiguration,
  oidcCookieName,
  publicOrigin,
  requiredMfaClaims,
  requiredStepUpClaims,
  secureCookies,
} from '../../../../src/oidc';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try {
    const origin = publicOrigin();
    const productionCookies = secureCookies();
    const accessName = productionCookies ? '__Host-nm_admin_access' : 'nm_admin_access';
    const csrfName = productionCookies ? '__Host-nm_admin_csrf' : 'nm_admin_csrf';
    const access = request.cookies.get(accessName)?.value;
    const csrf = request.cookies.get(csrfName)?.value;
    if (!access || !csrf) return NextResponse.redirect(new URL('/login', origin));

    const session = await fetch(apiUrl('/session'), {
      headers: { Accept: 'application/json', Cookie: `${accessName}=${encodeURIComponent(access)}; ${csrfName}=${encodeURIComponent(csrf)}` },
      cache: 'no-store',
      redirect: 'error',
    });
    const sessionBody = await session.json().catch(() => null) as { authenticated?: boolean; csrf_token?: string } | null;
    if (!session.ok || sessionBody?.authenticated !== true || sessionBody.csrf_token !== csrf) {
      return NextResponse.redirect(new URL('/unauthorized', origin));
    }

    const config = await oidcConfiguration();
    const stepUp = requiredStepUpClaims();
    requiredMfaClaims();
    const maxAge = Number(process.env.ADMIN_STEP_UP_MAX_AGE_SECONDS ?? 300);
    if (!Number.isInteger(maxAge) || maxAge < 1 || maxAge > 300) throw new Error('Invalid step-up max age');
    const returnTo = request.nextUrl.searchParams.get('returnTo') ?? '/';
    if (!returnTo.startsWith('/') || returnTo.startsWith('//') || returnTo.includes('\\')) throw new Error('Invalid return path');

    const codeVerifier = oidc.randomPKCECodeVerifier();
    const codeChallenge = await oidc.calculatePKCECodeChallenge(codeVerifier);
    const state = oidc.randomState();
    const nonce = oidc.randomNonce();
    const claims = stepUp.acr ? JSON.stringify({ id_token: { acr: { essential: true, values: [stepUp.acr] } } }) : undefined;
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
      max_age: String(maxAge),
      ...(claims ? { claims } : {}),
    });
    const response = NextResponse.redirect(authUrl);
    for (const [key, value] of Object.entries({ state, nonce, verifier: codeVerifier, flow: 'step-up', returnTo })) {
      response.cookies.set(oidcCookieName(key as 'state' | 'nonce' | 'verifier' | 'flow' | 'returnTo'), value, {
        httpOnly: true,
        secure: secureCookies(),
        sameSite: 'lax',
        path: '/',
        maxAge: 600,
      });
    }
    response.headers.set('Cache-Control', 'no-store');
    return response;
  } catch {
    return NextResponse.json({ error: 'Step-up authentication is not configured' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}
