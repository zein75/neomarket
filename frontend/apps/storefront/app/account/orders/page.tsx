import { OrdersPage } from '../../../src/OrdersPage';

export const metadata = { title: 'Заказы', robots: { index: false, follow: false } };

export default function OrdersRoute() {
  return <OrdersPage />;
}
