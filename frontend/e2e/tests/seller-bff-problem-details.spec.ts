import { expect, test } from '@playwright/test';
import { createHmac } from 'node:crypto';

const seller = process.env.NEOMARKET_SELLER_URL ?? 'http://127.0.0.1:3004';

test('Seller BFF route errors share the typed Problem Details envelope', async ({ request }) => {
  const endpoints = [
    { path: '/api/seller/auth/organizations', status: 401, code: 'AUTHENTICATION_REQUIRED' },
    { path: '/api/seller/categories', status: 401, code: 'AUTHENTICATION_REQUIRED' },
    { path: '/api/seller/imports/not-a-uuid', status: 400, code: 'INVALID_REQUEST' },
    { path: '/api/seller/orders', status: 401, code: 'AUTHENTICATION_REQUIRED' },
    { path: '/api/seller/products', status: 401, code: 'AUTHENTICATION_REQUIRED' },
    { path: '/api/seller/team/members', status: 401, code: 'AUTHENTICATION_REQUIRED' },
  ];

  for (const endpoint of endpoints) {
    const response = await request.get(`${seller}${endpoint.path}`);
    const problem = await response.json();
    const requestId = response.headers()['x-request-id'];

    expect(response.status(), endpoint.path).toBe(endpoint.status);
    expect(response.headers()['content-type'], endpoint.path).toContain('application/problem+json');
    expect(response.headers()['cache-control'], endpoint.path).toContain('no-store');
    expect(requestId, endpoint.path).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(problem, endpoint.path).toMatchObject({
      type: 'about:blank',
      status: endpoint.status,
      code: endpoint.code,
      requestId,
      trace_id: requestId,
    });
  }
});

test('Seller auth mutation errors use the shared Problem Details envelope', async ({ request }) => {
  const logout = await request.post(`${seller}/api/seller/auth/logout`, {
    headers: { Origin: seller, 'X-Request-ID': 'f45300bd-5ff1-4f1e-9fd5-a144464e0a68' },
  });
  const logoutProblem = await logout.json();
  expect(logout.status()).toBe(403);
  expect(logout.headers()['content-type']).toContain('application/problem+json');
  expect(logout.headers()['x-request-id']).toBe('f45300bd-5ff1-4f1e-9fd5-a144464e0a68');
  expect(logoutProblem).toMatchObject({
    status: 403,
    code: 'CSRF_VALIDATION_FAILED',
    requestId: 'f45300bd-5ff1-4f1e-9fd5-a144464e0a68',
    trace_id: 'f45300bd-5ff1-4f1e-9fd5-a144464e0a68',
  });

  const login = await request.post(`${seller}/api/seller/auth/login`, {
    headers: { Origin: seller },
    form: { username: '', password: '' },
  });
  const loginProblem = await login.json();
  expect(login.status()).toBe(400);
  expect(login.headers()['content-type']).toContain('application/problem+json');
  expect(login.headers()['x-request-id']).toBe(loginProblem.requestId);
  expect(loginProblem).toMatchObject({
    status: 400,
    code: 'INVALID_REQUEST',
    trace_id: loginProblem.requestId,
  });
});

test('Seller BFF validation errors use RFC 7807 and a correlated request ID', async ({ request }) => {
  const response = await request.get(`${seller}/api/seller/inventory?status=unknown`, {
    headers: { Cookie: 'nm_seller_access=local-contract-test' },
  });
  const problem = await response.json();
  const requestId = response.headers()['x-request-id'];

  expect(response.status()).toBe(422);
  expect(response.headers()['content-type']).toContain('application/problem+json');
  expect(response.headers()['cache-control']).toBe('no-store');
  expect(requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(problem).toMatchObject({
    type: 'about:blank',
    title: 'Seller inventory status is invalid',
    status: 422,
    code: 'INVALID_STATUS',
    requestId,
    trace_id: requestId,
  });
});

test('Seller category proxy propagates the request ID on a successful upstream response', async ({ request }) => {
  test.skip(process.env.NEOMARKET_BFF_RETRY_FIXTURE !== 'true', 'requires the local retry fixture as the configured B2B upstream');
  const requestId = '277d76f4-c868-4cb1-a467-2f8f52e367b2';
  const response = await request.get(`${seller}/api/seller/categories`, {
    headers: {
      Cookie: 'nm_seller_access=local-contract-test',
      'X-Request-ID': requestId,
    },
  });
  const body = await response.json();

  expect(response.status()).toBe(200);
  expect(response.headers()['x-request-id']).toBe(requestId);
  expect(response.headers()['cache-control']).toBe('no-store');
  expect(body).toEqual({ categories: [], request_id: requestId });
});

test('Seller inventory export download streams CSV and preserves safe download headers', async ({ request }) => {
  test.skip(process.env.NEOMARKET_BFF_RETRY_FIXTURE !== 'true', 'requires the local retry fixture as the configured B2B upstream');
  const requestId = '70c1664d-61aa-443d-9729-026d24187d70';
  const exportId = '5dd6739d-5829-4aa7-a681-2a035a98586b';
  const response = await request.get(`${seller}/api/seller/inventory/exports/${exportId}/download?token=local-signed-test-token`, {
    headers: {
      Cookie: 'nm_seller_access=local-contract-test',
      'X-Request-ID': requestId,
    },
  });
  const csv = await response.text();

  expect(response.status()).toBe(200);
  expect(response.headers()['x-request-id']).toBe(requestId);
  expect(response.headers()['cache-control']).toBe('private, no-store');
  expect(response.headers()['x-content-type-options']).toBe('nosniff');
  expect(response.headers()['content-type']).toContain('text/csv');
  expect(response.headers()['content-disposition']).toBe('attachment; filename="seller-export.csv"');
  expect(response.headers()['content-length']).toBeUndefined();
  expect(csv).toBe('sku,quantity\nSKU-001,7\n');
});

test('Seller inventory export download returns a correlated timeout when upstream headers stall', async ({ request }) => {
  test.skip(process.env.NEOMARKET_BFF_RETRY_FIXTURE !== 'true', 'requires the local retry fixture as the configured B2B upstream');
  const requestId = '78d139e6-124a-4698-bd18-6f49911776f5';
  const exportId = '5dd6739d-5829-4aa7-a681-2a035a98586b';
  const response = await request.get(`${seller}/api/seller/inventory/exports/${exportId}/download?token=slow-header`, {
    headers: {
      Cookie: 'nm_seller_access=local-contract-test',
      'X-Request-ID': requestId,
    },
  });
  const problem = await response.json();

  expect(response.status()).toBe(504);
  expect(response.headers()['content-type']).toContain('application/problem+json');
  expect(response.headers()['x-request-id']).toBe(requestId);
  expect(problem).toMatchObject({ status: 504, code: 'UPSTREAM_TIMEOUT', requestId, trace_id: requestId });
});

test('Seller BFF preserves a valid upstream request ID for correlation', async ({ request }) => {
  const requestId = 'd4be2bf7-31b9-4f34-8bc0-5f7aefb97c13';
  const response = await request.get(`${seller}/api/seller/dashboard/metrics`, {
    headers: { 'X-Request-ID': requestId },
  });
  const problem = await response.json();

  expect(response.status()).toBe(401);
  expect(response.headers()['x-request-id']).toBe(requestId);
  expect(problem.requestId).toBe(requestId);
  expect(problem.trace_id).toBe(requestId);
});

test('Seller BFF retries a transient read once and propagates its request ID', async ({ request }) => {
  test.skip(process.env.NEOMARKET_BFF_RETRY_FIXTURE !== 'true', 'requires the local retry fixture as the configured B2B upstream');
  await request.get('http://127.0.0.1:8013/__reset');
  const before = await (await request.get('http://127.0.0.1:8013/__state')).json();
  const requestId = 'b0fc9499-0ef9-4f54-85a2-3ae32cb1f954';
  const response = await request.get(`${seller}/api/seller/inventory?status=available`, {
    headers: {
      Cookie: 'nm_seller_access=local-contract-test',
      'X-Request-ID': requestId,
    },
  });
  const body = await response.json();
  const after = await (await request.get('http://127.0.0.1:8013/__state')).json();

  expect(response.status()).toBe(200);
  expect(after.read_attempts - before.read_attempts).toBe(2);
  expect(body.request_id).toBe(requestId);
  expect(response.headers()['x-request-id']).toBe(requestId);
});

test('Seller BFF retries a timed out read once and returns a correlated 504', async ({ request }) => {
  test.skip(process.env.NEOMARKET_BFF_RETRY_FIXTURE !== 'true', 'requires the local retry fixture as the configured B2B upstream');
  await request.get('http://127.0.0.1:8013/__reset');
  const before = await (await request.get('http://127.0.0.1:8013/__state')).json();
  const requestId = 'c432f50d-a1cc-43c5-9079-9582f71181f3';
  const response = await request.get(`${seller}/api/seller/inventory?status=inactive`, {
    headers: {
      Cookie: 'nm_seller_access=local-contract-test',
      'X-Request-ID': requestId,
    },
  });
  const problem = await response.json();
  const after = await (await request.get('http://127.0.0.1:8013/__state')).json();

  expect(response.status()).toBe(504);
  expect(problem.code).toBe('UPSTREAM_TIMEOUT');
  expect(problem.status).toBe(504);
  expect(problem.requestId).toBe(requestId);
  expect(response.headers()['x-request-id']).toBe(requestId);
  expect(after.read_attempts - before.read_attempts).toBe(2);
});

test('Seller BFF does not retry a product write after an upstream failure', async ({ request }) => {
  test.skip(process.env.NEOMARKET_BFF_RETRY_FIXTURE !== 'true', 'requires the local retry fixture as the configured B2B upstream');
  await request.get('http://127.0.0.1:8013/__reset');
  const before = await (await request.get('http://127.0.0.1:8013/__state')).json();
  const accessToken = 'local-contract-test';
  const csrfSecret = process.env.NEOMARKET_CSRF_SECRET;
  expect(csrfSecret).toBeTruthy();
  const csrfToken = createHmac('sha256', csrfSecret!).update(accessToken).digest('hex');
  const response = await request.post(`${seller}/api/seller/products`, {
    headers: {
      Origin: seller,
      Cookie: `nm_seller_access=${accessToken}; nm_seller_csrf=${csrfToken}`,
      'X-CSRF-Token': csrfToken,
      'Content-Type': 'application/json',
    },
    data: { title: 'QA product' },
  });
  const problem = await response.json();
  const after = await (await request.get('http://127.0.0.1:8013/__state')).json();

  expect(response.status()).toBe(503);
  expect(problem.title).toBe('Seller service is unavailable');
  expect(problem.code).toBe('TEMPORARY_FAILURE');
  expect(after.write_attempts - before.write_attempts).toBe(1);
});
