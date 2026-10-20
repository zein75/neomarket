const sensitiveKeys = new Set(['authorization', 'cookie', 'set-cookie', 'x-csrf-token', 'password', 'token', 'refresh_token', 'access_token']);

export function requestId(input?: string | null): string {
  return input && /^[a-zA-Z0-9._:-]{8,128}$/.test(input) ? input : crypto.randomUUID();
}

export function redactHeaders(headers: Headers | Record<string, string | undefined>): Record<string, string> {
  const result: Record<string, string> = {};
  const entries = headers instanceof Headers ? headers.entries() : Object.entries(headers);
  for (const [key, value] of entries) {
    if (!value) continue;
    result[key.toLowerCase()] = sensitiveKeys.has(key.toLowerCase()) ? '[REDACTED]' : value.slice(0, 256);
  }
  return result;
}

export function safeEvent(name: string, attributes: Record<string, string | number | boolean> = {}) {
  return { name: name.slice(0, 80), attributes: Object.fromEntries(Object.entries(attributes).filter(([key]) => !sensitiveKeys.has(key.toLowerCase()))) };
}
