import { SkusPage } from '../../../../src/SkusPage';

export default async function SellerSkusRoute({ params }: { params: Promise<{ id: string }> }) {
  return <SkusPage productId={(await params).id} />;
}
