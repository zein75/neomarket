export type SellerDecoder<T> = (value: unknown) => T;

export type SellerProblem = {
  type: string;
  title: string;
  status: number;
  code: string;
  requestId?: string;
  trace_id?: string;
  detail?: string;
  invalid_params?: Array<{ name: string; reason: string }>;
  [extension: string]: unknown;
};

export class SellerApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
    readonly problem?: SellerProblem,
  ) {
    super(message);
    this.name = 'SellerApiError';
  }
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function requestId(): string {
  if (typeof crypto === 'undefined') {
    return `00000000-0000-4000-8000-${Math.floor(Math.random() * 0x1000000000000).toString(16).padStart(12, '0')}`;
  }
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0'));
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`;
}

function isSellerProblem(value: unknown): value is SellerProblem {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const problem = value as Partial<SellerProblem>;
  return typeof problem.type === 'string'
    && typeof problem.title === 'string'
    && typeof problem.status === 'number'
    && typeof problem.code === 'string';
}

function upstreamProblem(value: unknown, status: number, correlationId: string): SellerApiError {
  if (isSellerProblem(value)) {
    return new SellerApiError(
      value.title,
      status,
      value.code,
      value.requestId ?? value.trace_id ?? correlationId,
      value,
    );
  }

  const legacy = value && typeof value === 'object' ? value as Record<string, unknown> : null;
  const detail = legacy?.detail && typeof legacy.detail === 'object'
    ? legacy.detail as Record<string, unknown>
    : null;
  const nestedDetail = detail?.message;
  const legacyCode = typeof detail?.code === 'string'
    ? detail.code
    : typeof legacy?.code === 'string'
      ? legacy.code
      : 'SELLER_REQUEST_FAILED';
  const title = typeof legacy?.title === 'string'
    ? legacy.title
    : typeof nestedDetail === 'string'
      ? nestedDetail
      : 'Не удалось выполнить запрос к Seller API';
  return new SellerApiError(title, status, legacyCode, correlationId);
}

function delay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal?.reason);
      return;
    }
    const cleanup = () => signal?.removeEventListener('abort', onAbort);
    const timer = setTimeout(() => { cleanup(); resolve(); }, milliseconds);
    const onAbort = () => {
      clearTimeout(timer);
      cleanup();
      reject(signal?.reason);
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export async function sellerApiRequest<T>(
  input: RequestInfo | URL,
  init: RequestInit,
  decode: SellerDecoder<T>,
  options: { timeoutMs?: number; retryRead?: boolean } = {},
): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase();
  const canRetry = options.retryRead !== false && (method === 'GET' || method === 'HEAD');
  const timeoutMs = options.timeoutMs ?? 8_000;
  const headers = new Headers(init.headers);
  const correlationId = headers.get('X-Request-ID');
  const safeCorrelationId = correlationId && UUID_PATTERN.test(correlationId) ? correlationId : requestId();
  headers.set('X-Request-ID', safeCorrelationId);
  headers.set('Accept', headers.get('Accept') ?? 'application/json');

  for (let attempt = 0; ; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(input, {
        ...init,
        headers,
        signal: AbortSignal.any([init.signal ?? new AbortController().signal, AbortSignal.timeout(timeoutMs)]),
      });
    } catch (error) {
      if (!canRetry || attempt > 0 || init.signal?.aborted) {
        if (error instanceof SellerApiError) throw error;
        const timedOut = error instanceof DOMException && error.name === 'TimeoutError';
        throw new SellerApiError(
          timedOut ? 'Seller API ответил слишком долго' : 'Seller API сейчас недоступен',
          timedOut ? 504 : 503,
          timedOut ? 'UPSTREAM_TIMEOUT' : 'DEPENDENCY_UNAVAILABLE',
          safeCorrelationId,
        );
      }
      await delay(150 * (attempt + 1), init.signal ?? undefined);
      continue;
    }

    if (canRetry && attempt === 0 && [502, 503, 504].includes(response.status)) {
      await response.body?.cancel();
      await delay(150, init.signal ?? undefined);
      continue;
    }

    const responseId = response.headers.get('X-Request-ID') ?? safeCorrelationId;
    if (!response.ok) {
      let body: unknown = null;
      try { body = await response.json(); } catch { /* non-JSON errors use the safe fallback */ }
      throw upstreamProblem(body, response.status, responseId);
    }

    if (response.status === 204 || response.status === 205) {
      return decode(undefined);
    }
    if (!response.headers.get('content-type')?.toLowerCase().includes('json')) {
      await response.body?.cancel();
      throw new SellerApiError('Seller API вернул неожиданный формат ответа', 502, 'INVALID_RESPONSE', responseId);
    }

    let payload: unknown;
    try {
      payload = await response.json();
      return decode(payload);
    } catch (error) {
      if (error instanceof SellerApiError) throw error;
      throw new SellerApiError('Seller API вернул данные неверного формата', 502, 'INVALID_RESPONSE', responseId);
    }
  }
}

export function sellerObject(value: unknown, path = 'response'): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${path} must be an object`);
  }
  return value as Record<string, unknown>;
}

export function sellerArray<T>(value: unknown, path: string, decode: SellerDecoder<T>): T[] {
  if (!Array.isArray(value)) throw new TypeError(`${path} must be an array`);
  return value.map((item, index) => decodeAt(item, decode, `${path}[${index}]`));
}

export function sellerString(value: unknown, path: string): string {
  if (typeof value !== 'string') throw new TypeError(`${path} must be a string`);
  return value;
}

export function sellerNumber(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(`${path} must be a finite number`);
  return value;
}

export function sellerInteger(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new TypeError(`${path} must be a safe integer`);
  return value;
}

export function sellerBoolean(value: unknown, path: string): boolean {
  if (typeof value !== 'boolean') throw new TypeError(`${path} must be a boolean`);
  return value;
}

export function sellerNullableString(value: unknown, path: string): string | null {
  return value === null ? null : sellerString(value, path);
}

export function sellerOptionalString(value: unknown, path: string): string | undefined {
  return value === undefined ? undefined : sellerString(value, path);
}

export function sellerOptionalNullableString(value: unknown, path: string): string | null | undefined {
  return value === undefined || value === null ? value : sellerString(value, path);
}

export function sellerOptionalBoolean(value: unknown, path: string): boolean | undefined {
  return value === undefined ? undefined : sellerBoolean(value, path);
}

export function sellerOptionalNumber(value: unknown, path: string): number | undefined {
  return value === undefined ? undefined : sellerNumber(value, path);
}

function decodeAt<T>(value: unknown, decode: SellerDecoder<T>, path: string): T {
  try {
    return decode(value);
  } catch (error) {
    throw new TypeError(error instanceof Error ? `${path}: ${error.message}` : `${path} is invalid`);
  }
}
