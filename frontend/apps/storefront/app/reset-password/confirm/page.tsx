import type { Metadata } from 'next';
import { PasswordResetForm } from '../../../src/PasswordResetForm';

export const metadata: Metadata = { title: 'Подтверждение восстановления', robots: { index: false, follow: false } };

export default async function ResetPasswordConfirmPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const params = await searchParams;
  return <PasswordResetForm confirm tokenPresent={typeof params.token === 'string' && params.token.length > 0} />;
}
