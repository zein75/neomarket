import { AdminShell } from '../../src/AdminPage';
import { AdminDashboard } from '../../src/AdminDashboard';

export default function DashboardPage() {
  return <AdminShell section="/dashboard"><AdminDashboard /></AdminShell>;
}
