import { NextResponse, type NextRequest } from 'next/server';
import * as oidc from 'openid-client';
import {
  apiUrl,
  claimMeetsMfa,
  claimMeetsStepUp,
  oidcConfiguration,
  oidcCookieName,
  publicOrigin,
  safeEqual,
  secureCookies,
} from '../../../../src/oidc';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function clearLoginCookies(response: NextResponse) {
  for (const key of ['state', 'nonce', 'verifier', 'flow', 'returnTo'] as const) {
    response.cookies.set(oidcCookieName(key), '', {
      httpOnly: true,
      secure: secureCookies(),
      sameSite: 'lax',
      path: '/',
      maxAge: 0,
    });
  }
}

function loginRedirect(origin: string, error: string) {
  const response = NextResponse.redirect(new URL(`/login?error=${error}`, origin));
  response.headers.set('Cache-Control', 'no-store');
  clearLoginCookies(response);
  return response;
}

export async function GET(request: NextRequest) {
  let origin: string;
  try {
    origin = publicOrigin();
    const stateCookie = request.cookies.get(oidcCookieName('state'))?.value;
    const nonce = request.cookies.get(oidcCookieName('nonce'))?.value;
    const verifier = request.cookies.get(oidcCookieName('verifier'))?.value;
    const flow = request.cookies.get(oidcCookieName('flow'))?.value;
    const returnTo = request.cookies.get(oidcCookieName('returnTo'))?.value ?? '/';
    const returnedState = request.nextUrl.searchParams.get('state') ?? '';
    if (!stateCookie || !nonce || !verifier || !['login', 'step-up'].includes(flow ?? '') || !safeEqual(stateCookie, returnedState)) {
      return loginRedirect(origin, 'invalid_response');
    }
    if (request.nextUrl.searchParams.has('error')) return loginRedirect(origin, 'authentication_failed');

    const config = await oidcConfiguration();
    const callbackUrl = new URL(`${origin}/api/auth/callback${request.nextUrl.search}`);
    const tokens = await oidc.authorizationCodeGrant(config, callbackUrl, {
      expectedState: stateCookie,
      expectedNonce: nonce,
      pkceCodeVerifier: verifier,
    });
    const claims = tokens.claims();
    if (!claims || typeof claims.sub !== 'string' || !claims.sub || !claimMeetsMfa(claims as Record<string, unknown>)) {
      return loginRedirect(origin, 'mfa_required');
    }
    if (!tokens.access_token) return loginRedirect(origin, 'authentication_failed');

    if (flow === 'step-up') {
      const accessName = secureCookies() ? '__Host-nm_admin_access' : 'nm_admin_access';
      const csrfName = secureCookies() ? '__Host-nm_admin_csrf' : 'nm_admin_csrf';
      const access = request.cookies.get(accessName)?.value;
      const csrf = request.cookies.get(csrfName)?.value;
      const authTime = Number(claims.auth_time);
      const maxAge = Number(process.env.ADMIN_STEP_UP_MAX_AGE_SECONDS ?? 300);
      const ageSeconds = Date.now() / 1000 - authTime;
      if (
        !access || !csrf || !claimMeetsStepUp(claims as Record<string, unknown>) ||
        !Number.isFinite(authTime) || ageSeconds < -60 || ageSeconds > maxAge ||
        !returnTo.startsWith('/') || returnTo.startsWith('//') || returnTo.includes('\\')
      ) return loginRedirect(origin, 'mfa_required');

      const stepUp = await fetch(apiUrl('/admin/v1/auth/step-up'), {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          Authorization: `Bearer ${tokens.access_token}`,
          Cookie: `${accessName}=${encodeURIComponent(access)}; ${csrfName}=${encodeURIComponent(csrf)}`,
          'X-CSRF-Token': csrf,
          'Sec-Fetch-Site': 'same-origin',
          Origin: origin,
        },
        cache: 'no-store',
        redirect: 'error',
      });
      if (stepUp.status !== 204) return loginRedirect(origin, 'access_unavailable');
      const destination = new URL(returnTo, origin);
      const response = NextResponse.redirect(destination);
      clearLoginCookies(response);
      response.headers.set('Cache-Control', 'no-store');
      return response;
    }

    const session = await fetch(apiUrl('/admin/v1/auth/session'), {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${tokens.access_token}`,
        Origin: origin,
      },
      cache: 'no-store',
      redirect: 'error',
    });
    if (session.status !== 201) return loginRedirect(origin, 'access_unavailable');

    const response = NextResponse.redirect(new URL('/', origin));
    for (const cookie of session.headers.getSetCookie()) response.headers.append('Set-Cookie', cookie);
    clearLoginCookies(response);
    response.headers.set('Cache-Control', 'no-store');
    return response;
  } catch {
    try {
      return loginRedirect(publicOrigin(), 'authentication_failed');
    } catch {
      return NextResponse.json({ error: 'Admin OIDC is not configured' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
    }
  }
}
