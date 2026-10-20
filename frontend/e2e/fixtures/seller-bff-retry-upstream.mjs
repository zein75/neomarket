import { createServer } from 'node:http';

let readAttempts = 0;
let writeAttempts = 0;

const server = createServer((request, response) => {
  if (request.url === '/__reset') {
    readAttempts = 0;
    writeAttempts = 0;
    response.writeHead(204).end();
    return;
  }

  if (request.url === '/__state') {
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ read_attempts: readAttempts, write_attempts: writeAttempts }));
    return;
  }

  if (request.url === '/api/v1/seller/categories' && request.method === 'GET') {
    const requestId = request.headers['x-request-id'];
    response.writeHead(200, { 'Content-Type': 'application/json', 'X-Request-ID': requestId });
    response.end(JSON.stringify({ categories: [], request_id: requestId }));
    return;
  }

  if (/^\/api\/v1\/seller\/inventory\/exports\/[0-9a-f-]+\/download\?token=/.test(request.url ?? '') && request.method === 'GET') {
    const requestId = request.headers['x-request-id'];
    if (request.url?.includes('token=slow-header')) {
      setTimeout(() => {
        if (!response.destroyed) response.writeHead(200, { 'Content-Type': 'text/csv; charset=utf-8' }).end('sku,quantity\n');
      }, 800);
      return;
    }
    response.writeHead(200, {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="seller-export.csv"',
      'X-Request-ID': requestId,
    });
    response.write('sku,quantity\n');
    setTimeout(() => response.end('SKU-001,7\n'), 10);
    return;
  }

  if (request.url?.startsWith('/api/v1/seller/inventory?') === true && request.method === 'GET') {
    readAttempts += 1;
    const requestId = request.headers['x-request-id'];
    if (request.url.includes('status=inactive')) {
      setTimeout(() => {
        if (!response.destroyed) {
          response.writeHead(200, { 'Content-Type': 'application/json', 'X-Request-ID': requestId });
          response.end(JSON.stringify({ items: [] }));
        }
      }, 800);
      return;
    }
    if (readAttempts === 1) {
      response.writeHead(503, { 'Content-Type': 'application/problem+json' }).end(JSON.stringify({
        type: 'about:blank', title: 'Inventory is temporarily unavailable', status: 503, code: 'TEMPORARY_FAILURE',
      }));
      return;
    }

    response.writeHead(200, { 'Content-Type': 'application/json', 'X-Request-ID': requestId });
    response.end(JSON.stringify({
      items: [],
      page: { has_more: false, next_cursor: null },
      mock_attempts: readAttempts,
      request_id: requestId,
    }));
    return;
  }

  if (request.url === '/api/v1/seller/products' && request.method === 'POST') {
    writeAttempts += 1;
    response.writeHead(503, { 'Content-Type': 'application/problem+json' }).end(JSON.stringify({
      type: 'about:blank',
      title: `Product write failed on attempt ${writeAttempts}`,
      status: 503,
      code: 'TEMPORARY_FAILURE',
    }));
    return;
  }

  {
    response.writeHead(404).end();
  }
});

server.listen(8013, '127.0.0.1', () => process.stdout.write('seller retry fixture listening on 127.0.0.1:8013\n'));

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
