import * as oidc from 'openid-client';
import { timingSafeEqual } from 'node:crypto';

export const OIDC_COOKIE_NAMES = {
  state: 'nm_admin_oidc_state',
  nonce: 'nm_admin_oidc_nonce',
  verifier: 'nm_admin_oidc_verifier',
  flow: 'nm_admin_oidc_flow',
  returnTo: 'nm_admin_oidc_return',
} as const;

export function secureCookies() {
  return !(process.env.NODE_ENV === 'development' && process.env.ADMIN_ALLOW_DEV_AUTH === 'true');
}

export function oidcCookieName(name: keyof typeof OIDC_COOKIE_NAMES) {
  return `${secureCookies() ? '__Host-' : ''}${OIDC_COOKIE_NAMES[name]}`;
}

export function publicOrigin() {
  const origin = process.env.NEOMARKET_PUBLIC_ORIGIN;
  if (!origin) throw new Error('Admin public origin is not configured');
  const parsed = new URL(origin);
  if (parsed.pathname !== '/' || parsed.search || parsed.hash || parsed.username || parsed.password) {
    throw new Error('Admin public origin must be an origin only');
  }
  const localDev = process.env.NODE_ENV === 'development' && process.env.ADMIN_ALLOW_DEV_AUTH === 'true';
  if (parsed.protocol !== 'https:' && !(localDev && parsed.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsed.hostname))) {
    throw new Error('Admin public origin must use HTTPS');
  }
  return parsed.origin;
}

function requiredEnv(name: string) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Admin OIDC is not configured: ${name}`);
  return value;
}

function oidcInternalBaseUrl() {
  const value = process.env.ADMIN_OIDC_INTERNAL_BASE_URL?.trim()
    || (process.env.NODE_ENV === 'production' ? 'http://keycloak:8080' : '');
  if (!value) return undefined;
  const parsed = new URL(value);
  if (
    !['http:', 'https:'].includes(parsed.protocol) ||
    !parsed.hostname ||
    parsed.pathname !== '/' && parsed.pathname !== '' ||
    parsed.search ||
    parsed.hash ||
    parsed.username ||
    parsed.password
  ) {
    throw new Error('ADMIN_OIDC_INTERNAL_BASE_URL must be a host-only internal URL');
  }
  if (parsed.protocol === 'http:' && !['keycloak', 'gateway'].includes(parsed.hostname)) {
    throw new Error('HTTP ADMIN_OIDC_INTERNAL_BASE_URL is restricted to the private staging network');
  }
  return parsed;
}

async function internalOidcFetch(url: string, options: oidc.CustomFetchOptions) {
  const internal = oidcInternalBaseUrl();
  if (!internal) return fetch(url, options as RequestInit);

  const requested = new URL(url);
  const publicIssuer = new URL(requiredEnv('ADMIN_OIDC_ISSUER'));
  if (requested.origin !== publicIssuer.origin) return fetch(url, options as RequestInit);

  const target = new URL(`${requested.pathname}${requested.search}`, internal);
  const headers = new Headers(options.headers as HeadersInit);
  headers.set('Host', publicIssuer.host);
  headers.set('X-Forwarded-Host', publicIssuer.host);
  headers.set('X-Forwarded-Proto', publicIssuer.protocol.slice(0, -1));
  try {
    return await fetch(target, { ...options, headers } as RequestInit);
  } catch (error) {
    const cause = error instanceof Error && error.cause instanceof Error
      ? `${error.cause.name}:${error.cause.message}`
      : error instanceof Error && error.cause
        ? String(error.cause)
        : 'none';
    console.error('Admin OIDC private fetch failed', `${target.origin}${target.pathname}`, cause);
    throw error;
  }
}

export function requiredMfaClaims() {
  const amr = process.env.ADMIN_OIDC_REQUIRED_AMR?.trim() ?? '';
  const acr = process.env.ADMIN_OIDC_REQUIRED_ACR?.trim() ?? '';
  if (!amr && !acr) throw new Error('Admin Keycloak MFA claim mapping is not configured');
  return { amr, acr };
}

export function requiredStepUpClaims() {
  const amr = process.env.ADMIN_OIDC_STEP_UP_REQUIRED_AMR?.trim() ?? '';
  const acr = process.env.ADMIN_OIDC_STEP_UP_REQUIRED_ACR?.trim() ?? '';
  if (!amr && !acr) throw new Error('Admin Keycloak step-up claim mapping is not configured');
  return { amr, acr };
}

export function isOidcReady() {
  try {
    requiredEnv('ADMIN_OIDC_ISSUER');
    requiredEnv('ADMIN_OIDC_CLIENT_ID');
    requiredEnv('ADMIN_OIDC_CLIENT_SECRET');
    requiredEnv('NEOMARKET_ADMIN_URL');
    requiredMfaClaims();
    publicOrigin();
    return true;
  } catch {
    return false;
  }
}

let configuration: Promise<oidc.Configuration> | undefined;

export function oidcConfiguration() {
  if (!configuration) {
    const internal = oidcInternalBaseUrl();
    const issuer = requiredEnv('ADMIN_OIDC_ISSUER');
    configuration = oidc.discovery(
      new URL(issuer),
      requiredEnv('ADMIN_OIDC_CLIENT_ID'),
      { client_secret: requiredEnv('ADMIN_OIDC_CLIENT_SECRET') },
      oidc.ClientSecretBasic(),
      internal ? { [oidc.customFetch]: internalOidcFetch } : undefined,
    ).catch((error: unknown) => {
      configuration = undefined;
      const cause = error instanceof Error && error.cause instanceof Error
        ? `${error.cause.name}:${error.cause.message}`
        : error instanceof Error && error.cause
          ? String(error.cause)
          : 'none';
      console.error(
        'Admin OIDC discovery failed',
        `issuer=${new URL(issuer).origin}`,
        `internal=${internal?.origin ?? 'none'}`,
        `cause=${cause}`,
      );
      throw error;
    });
  }
  return configuration;
}

export function claimMeetsMfa(claims: Record<string, unknown>) {
  const required = requiredMfaClaims();
  const amr = claims.amr;
  const validAmr = !required.amr || (Array.isArray(amr) && amr.includes(required.amr));
  const validAcr = !required.acr || claims.acr === required.acr;
  return validAmr && validAcr;
}

export function claimMeetsStepUp(claims: Record<string, unknown>) {
  const required = requiredStepUpClaims();
  const amr = claims.amr;
  const validAmr = !required.amr || (Array.isArray(amr) && amr.includes(required.amr));
  const validAcr = !required.acr || claims.acr === required.acr;
  return validAmr && validAcr;
}

export function safeEqual(left: string, right: string) {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function apiUrl(path: string) {
  const base = requiredEnv('NEOMARKET_ADMIN_URL').replace(/\/$/, '');
  return `${base}${path}`;
}
