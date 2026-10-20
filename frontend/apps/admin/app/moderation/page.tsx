import { AdminShell } from '../../src/AdminPage';
import { ModerationQueue } from '../../src/ModerationQueue';

export default function ModerationPage() {
  return <AdminShell section="/moderation"><ModerationQueue /></AdminShell>;
}
