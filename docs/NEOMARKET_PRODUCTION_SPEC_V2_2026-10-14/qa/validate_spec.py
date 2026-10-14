"""Validate authored NeoMarket target specs, not running business applications.
Run: python qa/validate_spec.py .
Requires: PyYAML and jsonschema; no network or DB access.
"""
import csv
import json
import re
import sys
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

root = Path(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parents[1])
errors = []
mds = list(root.rglob('*.md'))
for f in mds:
    s=f.read_text(encoding='utf-8')
    if not s.strip(): errors.append(f'{f.relative_to(root)} empty')
    if '\x00' in s: errors.append(f'{f.relative_to(root)} contains NUL byte')

for f in sorted((root/'contracts').glob('http-*.openapi.yaml')):
    doc=yaml.safe_load(f.read_text(encoding='utf-8'))
    if doc['openapi'] != '3.1.0': errors.append(f'{f.name}: wrong OAS version')
    if not doc.get('paths'): errors.append(f'{f.name}: no paths')
    ids=set()
    for path, methods in doc['paths'].items():
        for method, op in methods.items():
            if not op.get('security') and op.get('security') != []:
                errors.append(f'{f.name} {method} {path} no explicit security')
            if path.startswith('/internal/') and not any('mutualTLS' in sec and 'serviceBearer' in sec for sec in op.get('security',[])):
                errors.append(f'{f.name} {method} {path} missing dual internal security')
            opid=op.get('operationId')
            if opid in ids: errors.append(f'{f.name} duplicate operationId {opid}')
            ids.add(opid)
            if not op.get('responses'):errors.append(f'{f.name} {method} {path} missing responses')
    print(f'PASS YAML/route security {f.name}: {len(ids)} operations')

schemas={f.name:json.loads(f.read_text(encoding='utf-8')) for f in (root/'contracts').glob('*.schema.json')}
for name,doc in schemas.items():
    Draft202012Validator.check_schema(doc)
print(f'PASS JSON schema syntax: {len(schemas)} schemas')
example=json.loads((root/'contracts/product-created-example.json').read_text(encoding='utf-8'))
base='https://contracts.neomarket.example.invalid/'
registry=Registry().with_resources([(base+name,Resource.from_contents(doc)) for name,doc in schemas.items()])
for typ,fn,schema_file in [('product.created','product-created-example.json','product-event-v1.schema.json'),('moderation.approved','moderation-approved-example.json','moderation-event-v1.schema.json')]:
    try:
        payload=json.loads((root/'contracts'/fn).read_text(encoding='utf-8'))
        Draft202012Validator(schemas[schema_file],registry=registry).validate(payload)
        print(f'PASS sample {typ} contract')
    except Exception as e:
        errors.append(f'{typ} event sample failed: {e}')

with (root/'planning/RISK_TRACEABILITY.csv').open(encoding='utf-8-sig',newline='') as f:
    risk_rows=list(csv.DictReader(f))
if len(risk_rows) != 26:errors.append(f'traceability rows expected 26 got {len(risk_rows)}')
if len(set(row['risk_id'] for row in risk_rows)) != 26:errors.append('duplicate risk id')
for row in risk_rows:
    if not row['acceptance_tests'] or not row['spec_requirement'] or not row['implementation_steps']:
        errors.append(f"empty trace fields for {row['risk_id']}")
qa=(root/'qa/ACCEPTANCE_TEST_PLAN.md').read_text(encoding='utf-8')
for row in risk_rows:
    for tid in row['acceptance_tests'].split(';'):
        if tid not in qa: errors.append(f"missing test {tid} for {row['risk_id']}")
print(f'PASS risk mapping: {len(risk_rows)} rows')

# Verify nav links in README, excluding dynamic wildcard/URL text
readme=(root/'README.md').read_text(encoding='utf-8')
for fp in re.findall(r'`((?:spec|planning|contracts|qa|db|operations|evidence)/[^`*]+)`',readme):
    if not (root/fp).exists():errors.append(f'missing linked file {fp}')

if errors:
    print('\n'.join('FAIL '+e for e in errors))
    sys.exit(1)
print(f'PASS spec document checks: {len(mds)} markdown documents. Target specification consistency smoke complete.')
