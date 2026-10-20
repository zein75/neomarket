import type { Metadata } from 'next';
import { CheckoutStatusPage } from '../../../../src/CheckoutStatusPage';

export const metadata: Metadata = { title: 'Статус операции', robots: { index: false, follow: false } };

export default async function CheckoutOperationStatusRoute({ params }: { params: Promise<{ operationId: string }> }) {
  const { operationId } = await params;
  return <CheckoutStatusPage operationId={operationId} />;
}
