"""Fast static check; real effective Docker Compose config is checked on VPS."""
from pathlib import Path
import yaml
p=Path('deploy/staging/docker-compose.staging.yml')
data=yaml.safe_load(p.read_text(encoding='utf-8'))
services=data['services']
assert 'gateway' in services
for name, service in services.items():
    if name != 'gateway':
        assert not service.get('ports'), f'{name} publishes a host port!'
assert services['gateway']['ports'] == ['127.0.0.1:8080:80']
assert data['networks']['backend'].get('internal') is True
assert services['b2b']['environment']['REDIS_URL'].startswith('redis://:')
assert services['b2c']['environment']['REDIS_URL'].startswith('redis://:')
print('Static staging Compose security: PASS')
