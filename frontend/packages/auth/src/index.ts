export type AppRole = 'buyer' | 'seller' | 'admin';

export interface SessionDto {
  authenticated: boolean;
  role?: AppRole;
  displayName?: string;
  expiresAt?: string;
}

export const isPrivilegedRole = (role: AppRole | undefined): role is 'seller' | 'admin' => role === 'seller' || role === 'admin';
