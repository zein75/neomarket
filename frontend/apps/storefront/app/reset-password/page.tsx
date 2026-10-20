import type { Metadata } from 'next';
import { PasswordResetForm } from '../../src/PasswordResetForm';

export const metadata: Metadata = { title: 'Восстановление доступа', robots: { index: false, follow: false } };

export default function ResetPasswordPage() {
  return <PasswordResetForm />;
}
