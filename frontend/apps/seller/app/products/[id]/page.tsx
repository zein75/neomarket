import { ProductDetailPage } from '../../../src/ProductDetailPage';

export default async function SellerProductRoute({ params }: { params: Promise<{ id: string }> }) {
  return <ProductDetailPage productId={(await params).id} />;
}
