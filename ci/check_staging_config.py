"""Fast static check; real effective Docker Compose config is checked on VPS."""
from pathlib import Path
import yaml
p=Path('deploy/staging/docker-compose.staging.yml')
data=yaml.safe_load(p.read_text(encoding='utf-8'))
services=data['services']
admin_env=services['admin']['environment']
assert admin_env['APP_ENV'] == 'production'
assert admin_env['ADMIN_ALLOW_DEV_AUTH'] == 'false', 'staging Admin must disable development identity bypass'
assert services['admin-worker']['environment']['ADMIN_ALLOW_DEV_AUTH'] == 'false'
assert 'gateway' in services
assert 'clamd' in services, 'staging must include a real ClamAV scanner'
assert services['clamd']['image'] == 'clamav/clamav:1.5.4'
assert services['clamd']['dns'] == ['192.168.0.1'], 'ClamAV update container must use the staging LAN DNS resolver'
assert not services['clamd'].get('ports'), 'ClamAV must not publish a host port'
assert set(services['clamd']['networks']) == {'backend', 'egress'}, 'ClamAV must use private backend plus dedicated egress network'
assert 'clamavdata:/var/lib/clamav' in services['clamd']['volumes']
assert services['clamd']['healthcheck']['test'][0] == 'CMD-SHELL'
assert 'keycloak' in services and 'keycloak-postgres' in services
assert services['keycloak']['image'] == 'quay.io/keycloak/keycloak:26.3.2'
assert services['keycloak']['environment']['KC_DB'] == 'postgres'
assert not services['keycloak'].get('ports')
assert 'mailpit' in services and not services['mailpit'].get('ports')
assert services['mailpit']['healthcheck']['test'][0] == 'CMD-SHELL'
assert services['mailpit']['healthcheck']['test'][1] == '/mailpit readyz'
for frontend in ('storefront', 'seller-frontend', 'admin-frontend'):
    assert frontend in services, f'missing staging frontend service: {frontend}'
    assert ':${RELEASE_SHA}' in services[frontend]['image'], f'{frontend} must use immutable release image'
    assert services[frontend]['healthcheck']['test'][0] == 'CMD-SHELL'
    assert frontend in services['gateway']['depends_on'], f'gateway must wait for {frontend}'
assert services['b2c']['environment']['RECOVERY_WORKER_ENABLED'] == 'false'
assert services['b2b']['environment']['MEDIA_SCANNER_HOST'] == 'clamd'
assert services['b2b']['environment']['MEDIA_SCANNER_PORT'] == '3310'
assert 'media_data:/app/media' in services['b2b']['volumes']
assert services['b2b']['depends_on']['clamd']['condition'] == 'service_healthy'
assert services['b2b']['depends_on']['mailpit']['condition'] == 'service_healthy'
assert services['b2c-recovery-worker']['environment']['RECOVERY_WORKER_ENABLED'] == 'true'
assert 'ports' not in services['b2c-recovery-worker'] or not services['b2c-recovery-worker']['ports']
for name, service in services.items():
    if name != 'gateway':
        assert not service.get('ports'), f'{name} publishes a host port!'
assert services['gateway']['ports'] == ['127.0.0.1:18080:80']
assert data['networks']['backend'].get('internal') is True
assert 'egress' in data['networks'] and data['networks']['egress'].get('internal') is not True
assert set(services['admin']['networks']) == {'backend', 'admin-data'}
assert set(services['admin-frontend']['networks']) == {'backend'}
assert 'edge' not in services['admin']['networks']
assert 'edge' not in services['admin-frontend']['networks']
nginx=Path('deploy/staging/nginx.conf').read_text(encoding='utf-8')
assert 'server_name _;' in nginx and 'return 444;' in nginx, 'staging gateway must reject unknown public hosts'
assert 'server_name admin.internal admin.neomarket.test;' in nginx, 'Admin UI must use its dedicated internal host'
assert 'upstream admin_api' not in nginx, 'Admin API must not be routed directly by the public gateway'
assert services['b2b']['environment']['REDIS_URL'].startswith('redis://:')
assert services['b2c']['environment']['REDIS_URL'].startswith('redis://:')
production=yaml.safe_load(Path('docker-compose.prod.yaml').read_text(encoding='utf-8'))
production_admin_env=production['services']['admin']['environment']
assert production_admin_env['APP_ENV'] == 'production'
assert production_admin_env['ADMIN_ALLOW_DEV_AUTH'] == 'false', 'production Admin must disable development identity bypass'
print('Static staging Compose security: PASS')
