import { SellerOrderDetailPage } from '../../../src/SellerOrderDetailPage';

export default async function SellerOrderRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SellerOrderDetailPage orderId={id} />;
}
