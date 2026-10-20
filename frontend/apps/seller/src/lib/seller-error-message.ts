import { SellerApiError } from './seller-api';

export function sellerErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof SellerApiError && ['DEPENDENCY_UNAVAILABLE', 'UPSTREAM_TIMEOUT'].includes(error.code)) return fallback;
  return error instanceof TypeError ? fallback : error instanceof Error ? error.message : fallback;
}
