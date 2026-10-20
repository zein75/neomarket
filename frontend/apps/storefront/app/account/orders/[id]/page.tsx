import { OrderDetailPage } from '../../../../src/OrderDetailPage';

export const metadata = { title: 'Заказ', robots: { index: false, follow: false } };

export default async function OrderDetailRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <OrderDetailPage orderId={id} />;
}
