import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';

export type SellerProblemDetails = {
  type: string;
  title: string;
  status: number;
  code: string;
  requestId: string;
  trace_id: string;
  detail?: string;
  invalid_params?: Array<{ name: string; reason: string }>;
  [extension: string]: unknown;
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const requestIds = new WeakMap<Request, string>();

const statusCodes: Record<number, string> = {
  400: 'INVALID_REQUEST',
  401: 'AUTHENTICATION_REQUIRED',
  403: 'ACCESS_DENIED',
  404: 'NOT_FOUND',
  409: 'CONFLICT',
  412: 'REVISION_CONFLICT',
  422: 'VALIDATION_FAILED',
  429: 'RATE_LIMITED',
  502: 'DEPENDENCY_UNAVAILABLE',
  503: 'DEPENDENCY_UNAVAILABLE',
  504: 'UPSTREAM_TIMEOUT',
};

const safeTitles: Record<number, string> = {
  400: 'Request is invalid',
  401: 'Seller authentication is required',
  403: 'Seller action is not permitted',
  404: 'Seller resource was not found',
  409: 'Seller request conflicts with current state',
  412: 'Seller resource has changed',
  422: 'Seller request could not be validated',
  429: 'Too many requests',
  502: 'Seller service is unavailable',
  503: 'Seller service is unavailable',
  504: 'Seller service timed out',
};

export function sellerStatusCode(status: number): string {
  return statusCodes[status] ?? 'SELLER_REQUEST_FAILED';
}

export function sellerRequestId(request: Request): string {
  const cached = requestIds.get(request);
  if (cached) return cached;
  const supplied = request.headers.get('x-request-id');
  const requestId = supplied && UUID_PATTERN.test(supplied) ? supplied : randomUUID();
  requestIds.set(request, requestId);
  return requestId;
}

export function sellerProblemResponse(
  request: Request | null,
  status: number,
  title: string,
  code: string,
  detail?: string,
  options?: { cacheControl?: string; headers?: HeadersInit; extensions?: Record<string, unknown> },
): NextResponse<SellerProblemDetails> {
  const requestId = request ? sellerRequestId(request) : randomUUID();
  const problem: SellerProblemDetails = {
    ...options?.extensions,
    type: 'about:blank',
    title,
    status,
    code,
    requestId,
    trace_id: requestId,
    ...(detail ? { detail } : {}),
  };

  const headers = new Headers(options?.headers);
  headers.set('Cache-Control', options?.cacheControl ?? headers.get('Cache-Control') ?? 'no-store');
  headers.set('Content-Type', 'application/problem+json; charset=utf-8');
  headers.set('X-Request-ID', requestId);
  return NextResponse.json(problem, { status, headers });
}

export function sellerProblem(
  status: number,
  title: string,
  options?: { cacheControl?: string; headers?: HeadersInit; extensions?: Record<string, unknown> },
): NextResponse<SellerProblemDetails> {
  return sellerProblemResponse(null, status, title, sellerStatusCode(status), undefined, options);
}

export function sellerCommercialFlowDisabledResponse(request: Request, flow: string): NextResponse<SellerProblemDetails> {
  return sellerProblemResponse(
    request,
    503,
    'Seller fulfillment actions are disabled until commercial policy is approved',
    'COMMERCIAL_FLOW_DISABLED',
    'Order acceptance, packing and dispatch are unavailable pending the required ADRs.',
    { extensions: { flow, feature_status: 'disabled_pending_adr' } },
  );
}

export function sellerJsonResponse<T>(request: Request, body: T, init?: ResponseInit): NextResponse<T> {
  const headers = new Headers(init?.headers);
  headers.set('Cache-Control', headers.get('Cache-Control') ?? 'no-store');
  headers.set('X-Request-ID', sellerRequestId(request));
  return NextResponse.json(body, { ...init, headers });
}

export async function sellerUpstreamFetch(
  request: Request,
  input: string,
  init: RequestInit,
  timeoutMs = 8_000,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-Request-ID', sellerRequestId(request));
  const method = (init.method ?? 'GET').toUpperCase();
  const canRetry = method === 'GET' || method === 'HEAD';
  const configuredTimeout = Number(process.env.NEOMARKET_BFF_UPSTREAM_TIMEOUT_MS);
  const effectiveTimeout = Number.isInteger(configuredTimeout) && configuredTimeout >= 50 && configuredTimeout <= 30_000
    ? configuredTimeout
    : timeoutMs;

  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await fetch(input, {
        ...init,
        headers,
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(effectiveTimeout)]),
      });
      if (canRetry && attempt === 0 && [502, 503, 504].includes(response.status)) {
        await response.body?.cancel();
        await new Promise((resolve) => setTimeout(resolve, 150));
        continue;
      }
      const body = await response.text();
      return new Response(body || null, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    } catch (error) {
      if (!canRetry || attempt > 0 || request.signal.aborted) throw error;
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
  }
}

export async function sellerStreamingUpstreamFetch(
  request: Request,
  input: string,
  init: RequestInit,
  headersTimeoutMs = 8_000,
  idleTimeoutMs = 30_000,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-Request-ID', sellerRequestId(request));
  const configuredTimeout = Number(process.env.NEOMARKET_BFF_UPSTREAM_TIMEOUT_MS);
  const effectiveHeadersTimeout = Number.isInteger(configuredTimeout) && configuredTimeout >= 50 && configuredTimeout <= 30_000
    ? configuredTimeout
    : headersTimeoutMs;
  const abortController = new AbortController();
  const abortFromRequest = () => abortController.abort(request.signal.reason);
  if (request.signal.aborted) abortFromRequest();
  else request.signal.addEventListener('abort', abortFromRequest, { once: true });

  const timeout = setTimeout(
    () => abortController.abort(new DOMException('Seller upstream response headers timed out', 'TimeoutError')),
    effectiveHeadersTimeout,
  );
  let upstream: Response;
  try {
    upstream = await fetch(input, { ...init, headers, signal: abortController.signal });
  } catch (error) {
    request.signal.removeEventListener('abort', abortFromRequest);
    if (abortController.signal.reason instanceof DOMException) throw abortController.signal.reason;
    throw error;
  } finally {
    clearTimeout(timeout);
  }

  if (!upstream.body || [204, 205, 304].includes(upstream.status)) {
    request.signal.removeEventListener('abort', abortFromRequest);
    return new Response(null, { status: upstream.status, statusText: upstream.statusText, headers: upstream.headers });
  }

  const reader = upstream.body.getReader();
  let finished = false;
  const cleanup = () => request.signal.removeEventListener('abort', abortFromRequest);
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (finished) return;
      let idleTimer: ReturnType<typeof setTimeout> | undefined;
      try {
        const result = await Promise.race([
          reader.read(),
          new Promise<never>((_, reject) => {
            idleTimer = setTimeout(() => {
              const reason = new DOMException('Seller upstream response body timed out', 'TimeoutError');
              abortController.abort(reason);
              void reader.cancel(reason);
              reject(reason);
            }, idleTimeoutMs);
          }),
        ]);
        if (idleTimer) clearTimeout(idleTimer);
        if (result.done) {
          finished = true;
          cleanup();
          controller.close();
        } else {
          controller.enqueue(result.value);
        }
      } catch (error) {
        if (idleTimer) clearTimeout(idleTimer);
        finished = true;
        cleanup();
        controller.error(error);
      }
    },
    async cancel(reason) {
      finished = true;
      cleanup();
      abortController.abort(reason);
      await reader.cancel(reason);
    },
  });

  return new Response(body, { status: upstream.status, statusText: upstream.statusText, headers: upstream.headers });
}

export async function sellerUpstreamResponse(
  request: Request,
  upstream: Response,
  options?: { cacheControl?: string },
): Promise<NextResponse> {
  const requestId = sellerRequestId(request);
  const body = await upstream.text();
  if (!upstream.ok) {
    let payload: unknown;
    if (upstream.headers.get('content-type')?.includes('json')) {
      try { payload = JSON.parse(body); } catch { payload = null; }
    }
    const candidate = payload && typeof payload === 'object' ? payload as Record<string, unknown> : null;
    const title = safeTitles[upstream.status] ?? 'Seller request could not be completed';
    const candidateCode = candidate?.code;
    const code = typeof candidateCode === 'string' && /^[A-Z0-9_]{2,64}$/.test(candidateCode)
      ? candidateCode
      : sellerStatusCode(upstream.status);
    const retryAfter = upstream.headers.get('retry-after');
    return sellerProblemResponse(
      request,
      upstream.status,
      title,
      code,
      undefined,
      retryAfter ? { headers: { 'Retry-After': retryAfter } } : undefined,
    );
  }

  const headers = new Headers({
    'Cache-Control': options?.cacheControl ?? 'no-store',
    'X-Request-ID': requestId,
  });
  const contentType = upstream.headers.get('content-type');
  if (contentType) headers.set('Content-Type', contentType);
  for (const name of ['etag', 'location', 'retry-after', 'idempotency-replayed']) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (upstream.status === 204 || upstream.status === 205 || upstream.status === 304) {
    return new NextResponse(null, { status: upstream.status, headers });
  }
  return new NextResponse(body, { status: upstream.status, headers });
}

export async function sellerStreamingResponse(
  request: Request,
  upstream: Response,
  options?: { cacheControl?: string; headers?: HeadersInit },
): Promise<NextResponse> {
  if (!upstream.ok) {
    return sellerUpstreamResponse(request, upstream, options);
  }
  const headers = new Headers(options?.headers);
  for (const name of ['content-type', 'content-length', 'content-disposition', 'etag', 'accept-ranges']) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set('Cache-Control', options?.cacheControl ?? 'no-store');
  headers.set('X-Request-ID', sellerRequestId(request));
  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

export function isSellerUpstreamTimeout(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'TimeoutError';
}
