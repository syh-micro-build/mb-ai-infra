#!/usr/bin/env python3
"""Deterministic controller-side rendering; no host or Docker mutations."""
import argparse
import hashlib
import json
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from infra import validate_config

REPO = Path(__file__).resolve().parent.parent


def load_config(site):
    config = yaml.safe_load((REPO / 'ansible/vars/defaults.yml').read_text())['infra_defaults']
    config.update(yaml.safe_load(Path(site).read_text()).get('infra_site', {}))
    config['contracts'] = [yaml.safe_load((REPO / f'contracts/{name}.yml').read_text()) for name in ('sub2api', 'docs')]
    validate_config(config)
    return config


def render(config, release_path, tls=True):
    validate_config(config)
    env = Environment(loader=FileSystemLoader(REPO / 'edge'), undefined=StrictUndefined, keep_trailing_newline=True)
    ctx = dict(infra_config=config, release_path=str(release_path), edge_tls_enabled=tls)
    files = {
        'config.json': json.dumps(dict(config, tls_enabled=tls), sort_keys=True, indent=2) + '\n',
        'compose.yaml': env.get_template('compose.yaml.j2').render(**ctx),
        'nginx/nginx.conf': env.get_template('nginx/nginx.conf.j2').render(**ctx),
        'nginx/conf.d/site.conf': env.get_template('nginx/site.conf.j2').render(**ctx),
        'nginx/conf.d/proxy.inc': (REPO / 'edge/nginx/proxy.inc').read_text(),
    }
    manifest = {'version': (REPO / 'VERSION').read_text().strip(), 'files': {
        path: hashlib.sha256(body.encode()).hexdigest() for path, body in files.items()}}
    files['manifest.json'] = json.dumps(manifest, sort_keys=True, indent=2) + '\n'
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--site', default='ansible/inventory/example/group_vars/mb_ai.yml')
    parser.add_argument('--output', required=True)
    parser.add_argument('--runtime-path', help='Absolute target release path; defaults to output')
    parser.add_argument('--http-only', action='store_true')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    for path, body in render(load_config(args.site), args.runtime_path or output.as_posix(), not args.http_only).items():
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8', newline='\n')
    print(f'Rendered {output}')


if __name__ == '__main__':
    main()
