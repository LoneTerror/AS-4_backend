import sys, os
from pathlib import Path

env_file = Path('.env')
for line in env_file.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, _, val = line.partition('=')
    key, val = key.strip(), val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in (chr(34), chr(39)):
        val = val[1:-1]
    os.environ.setdefault(key, val)

sys.path.insert(0, '.')

import importlib
from fastapi.routing import APIRoute

services = [
    ('auth',         'src.auth.main',         'app'),
    ('roles',        'src.roles.main',        'app'),
    ('employees',    'src.employees.main',    'app'),
    ('wallet',       'src.wallet.main',       'app'),
    ('recognition',  'src.recognition.main',  'app'),
    ('rewards',      'src.rewards.main',      'app'),
    ('organization', 'src.organization.main', 'app'),
    ('analytics',    'src.analytics.main',    'app'),
]

skip = {'/health','/v1/docs','/v1/redoc','/v1/openapi.json','/openapi.json','/docs','/redoc'}

for name, module_path, app_attr in services:
    try:
        mod = importlib.import_module(module_path)
        app = getattr(mod, app_attr)
        print(f'\n# -- {name}')
        routes = []
        for route in app.routes:
            if not isinstance(route, APIRoute): continue
            if route.path in skip: continue
            if any(route.path.startswith(s) for s in ['/docs','/redoc','/openapi']): continue
            for method in sorted(route.methods or []):
                routes.append(f'  {method:<7} {route.path}')
        for r in sorted(routes):
            print(r)
    except Exception as e:
        print(f'  ERROR loading {name}: {e}')
