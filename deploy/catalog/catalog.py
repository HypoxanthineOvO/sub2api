#!/usr/bin/env python3
"""Validate and prepare public /vsp/models data; no network or production writes."""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

MAX_BYTES = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON member')
        result[key] = value
    return result


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def public_metadata(value):
    if isinstance(value, dict):
        for key, child in value.items():
            require(key.replace('_', '').lower() not in {
                'apikey', 'password', 'accesstoken', 'refreshtoken', 'authorization', 'bearertoken', 'clientsecret'
            }, 'public metadata must not contain credential fields')
            public_metadata(child)
    elif isinstance(value, list):
        for child in value:
            public_metadata(child)


def validate(raw, previous=None):
    require(len(raw) <= MAX_BYTES, 'catalog exceeds 4 MiB')
    data = json.loads(raw, object_pairs_hook=object_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON number')))
    require(isinstance(data, dict), 'catalog must be an object')
    public_metadata(data)
    require(type(data.get('version', 1)) is int and data.get('version', 1) == 1, 'unsupported schema version')
    models = data.get('models')
    if 'pricingBasis' in data:
        basis = data['pricingBasis']
        require(isinstance(basis, dict) and isinstance(basis.get('purpose'), str), 'invalid pricing basis')
        require(basis.get('currency', 'USD') == 'USD' and basis.get('perTokens', 1000000) == 1000000, 'prices must use USD per million tokens')
    require(isinstance(models, list) and len(models) <= 10000, 'invalid models array')
    ids = set()
    old = {m['id']: m for m in previous['models']} if previous else {}
    for model in models:
        require(isinstance(model, dict), 'model must be an object')
        key = model.get('id')
        require(isinstance(key, str) and 0 < len(key) <= 200 and key == key.strip(), 'invalid model ID')
        require(not any(ord(char) < 32 for char in key), 'control character in model ID')
        require(key not in ids, 'duplicate model ID')
        ids.add(key)
        for name in ('contextWindow', 'maxTokens', 'effortRevision'):
            if name in model:
                require(type(model[name]) is int and model[name] > 0, f'invalid {name}')
        for name in ('hidden', 'curated', 'reasoning'):
            if name in model:
                require(type(model[name]) is bool, f'invalid {name}')
        for name in ('name', 'protocol', 'defaultEffort'):
            if name in model:
                require(isinstance(model[name], str) and model[name].strip(), f'invalid {name}')
        if 'protocol' in model:
            require(model['protocol'] in ('openai', 'openai_responses', 'anthropic', 'google-genai'), 'extend protocol adapters before adding a new protocol')
        for name in ('input', 'effortLevels', 'capabilities'):
            if name in model:
                values = model[name]
                require(isinstance(values, list) and all(isinstance(v, str) and v.strip() for v in values), f'invalid {name}')
        if 'effortRevision' in model:
            require(bool(model.get('effortLevels')) or model.get('reasoning') is False, 'versioned effort requires levels')
        if 'defaultEffort' in model and 'effortLevels' in model:
            require(model['defaultEffort'] in model['effortLevels'], 'default effort is not declared')
        if 'effortMode' in model:
            require(model['effortMode'] in ('effort', 'toggle'), 'invalid effort mode')
        if 'releasedAt' in model:
            require(isinstance(model['releasedAt'], str), 'invalid release date')
            require(dt.date.fromisoformat(model['releasedAt']).isoformat() == model['releasedAt'], 'invalid release date')
        if 'cost' in model:
            cost = model['cost']
            require(isinstance(cost, dict), 'cost must be an object')
            for name in ('input', 'output', 'cacheRead', 'cacheWrite', 'reasoning'):
                if name in cost:
                    require(finite(cost[name]) and cost[name] >= 0, 'invalid price')
            if 'tiers' in cost:
                require(isinstance(cost['tiers'], list), 'invalid price tiers')
                for tier in cost['tiers']:
                    require(isinstance(tier, dict), 'invalid price tier')
                    require(all(finite(tier.get(name)) and tier[name] >= 0 for name in ('input', 'output')), 'invalid tier price')
                    threshold = tier.get('tier')
                    require(isinstance(threshold, dict) and isinstance(threshold.get('type'), str), 'invalid tier threshold')
                    require(type(threshold.get('size')) is int and threshold['size'] > 0, 'invalid tier size')
        if key in old:
            require(model.get('effortRevision', 0) >= old[key].get('effortRevision', 0), 'effort revision regressed')
    # No entitlement lookup, provider probes or filtering, including hidden entries.
    return data


def prepare(source, output, previous=None):
    source = Path(source).resolve()
    raw = source.read_bytes()
    data = validate(raw, validate(Path(previous).read_bytes()) if previous else None)
    repo = Path(subprocess.check_output(['git', '-C', str(source.parent), 'rev-parse', '--show-toplevel'], text=True).strip())
    relative = source.relative_to(repo).as_posix()
    committed = subprocess.check_output(['git', '-C', str(repo), 'show', f'HEAD:{relative}'])
    require(raw == committed, 'commit the authoritative catalog before preparing it')
    commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    digest = hashlib.sha256(raw).hexdigest()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / digest
    require(not destination.exists(), 'artifact already exists; do not overwrite immutable data')
    with tempfile.TemporaryDirectory(prefix='.catalog-', dir=output) as temp:
        root = Path(temp)
        (root / 'model-catalog.json').write_bytes(raw)
        (root / 'manifest.json').write_text(json.dumps({
            'format': 1, 'sourceCommit': commit, 'sourcePath': relative,
            'sha256': digest, 'schemaVersion': data.get('version', 1), 'modelCount': len(data['models'])
        }, indent=2) + '\n')
        root.rename(destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='committed authoritative model-catalog.json')
    parser.add_argument('--output', type=Path, help='prepare immutable artifact directory; omit to validate only')
    parser.add_argument('--previous', type=Path, help='previous catalog, for effort-revision regression checks')
    args = parser.parse_args()
    try:
        if args.output:
            print(prepare(args.source, args.output, args.previous))
        else:
            data = validate(Path(args.source).read_bytes(), validate(args.previous.read_bytes()) if args.previous else None)
            print(f"VALID: {len(data['models'])} model declarations; no availability filtering")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'catalog preparation failed: {error}\n')
