import { execFileSync } from 'node:child_process';

/** Clears only the local B2B login IP counter so sequential browser suites do not throttle each other. */
export function resetLocalLoginIpCounter() {
  const digest = execFileSync(
    'docker',
    ['exec', '-i', 'neomarket-b2b-1', 'uv', 'run', 'python', '-c', "from src.services.login_rate_limiter import _digest; print(_digest('172.19.0.1'))"],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
  ).trim();
  execFileSync('docker', ['exec', 'neomarket-redis-1', 'redis-cli', 'DEL', `b2b:login:ip:${digest}`], { stdio: 'ignore' });
}
