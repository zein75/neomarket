import { Storefront } from '../../src/Storefront';
export const metadata = { title: 'Корзина', robots: { index: false, follow: false } };
export default function CartPage() { return <Storefront initialView="cart" />; }
