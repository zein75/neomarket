import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { Storefront } from '../../src/Storefront';
export const metadata = { title: 'Оформление заказа', robots: { index: false, follow: false } };
export default async function CheckoutPage() {
  const cookieStore = await cookies();
  if (!cookieStore.get('nm_access') && !cookieStore.get('__Host-nm_access')) redirect('/login?next=%2Fcheckout');
  return <Storefront initialView="checkout" />;
}
