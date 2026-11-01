#!/usr/bin/env python3
"""Restore omitted DriverKit headers from Apple's earlier Darwin 23 source."""
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request

# Tags of the Apple sources that still carry the headers newer xnu omits; feeds.toml sets them for the unixnu driver.
TAG = os.environ.get('UNIXNU_DRIVERKIT_TAG', 'xnu-10063.121.3')
TRUST_TAG = os.environ.get('UNIXNU_TRUSTCACHE_TAG', 'xnu-8796.101.5')
DESTINATION = Path('.cache/xnu-work/iokit/DriverKit')
CACHE = Path(f'.cache/sources/xnu-driverkit-{TAG.removeprefix("xnu-")}.json')
URL = f'https://api.github.com/repos/apple-oss-distributions/xnu/contents/iokit/DriverKit?ref={TAG}'
LOCAL_DIR = Path(__file__).resolve().parent / 'omitted-headers'

HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}


def fetch_url(url, timeout=30):
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    return urllib.request.urlopen(req, timeout=timeout).read()


def restore(entry, destination=DESTINATION, tag=TAG):
    if entry.get('type') != 'file' or not entry.get('name', '').endswith('.h'):
        return None
    name = entry.get('relative', entry['name'])
    target = destination / name
    if target.exists():
        return None

    data = None

    # 1. Check local pre-bundled offline cache
    candidates = [
        LOCAL_DIR / ('iokit/DriverKit' if destination == DESTINATION else 'EXTERNAL_HEADERS/TrustCache') / name,
        LOCAL_DIR / name,
        LOCAL_DIR / entry['name'],
    ]
    for cand in candidates:
        if cand.is_file():
            data = cand.read_bytes()
            break

    # 2. Check git_url via GitHub API (base64 blob)
    if data is None and entry.get('git_url'):
        try:
            res_json = json.loads(fetch_url(entry['git_url'], timeout=15))
            if 'content' in res_json:
                data = base64.b64decode(res_json['content'])
        except Exception:
            pass

    # 3. Check mirrors and direct download_url
    if data is None and entry.get('download_url'):
        dl = entry['download_url']
        for test_url in [f'https://ghfast.top/{dl}', f'https://ghproxy.net/{dl}', dl]:
            try:
                data = fetch_url(test_url, timeout=15)
                if data:
                    break
            except Exception:
                continue

    if data is None:
        raise RuntimeError(f'Failed to fetch header {name} from both local cache and network')

    digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if digest != entry['sha']:
        raise ValueError(f'Git blob hash mismatch: {entry["name"]}')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {'name': name, 'source_tag': tag, 'git_blob': digest,
            'sha256': hashlib.sha256(data).hexdigest()}


if __name__ == '__main__':
    if not DESTINATION.is_dir():
        raise SystemExit('Create the local XNU work source before preparing headers')

    # Ensure .cache/sources directory exists
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    # 1. DriverKit json cache
    if not CACHE.exists():
        local_cache = LOCAL_DIR / CACHE.name
        if local_cache.is_file():
            shutil.copy2(local_cache, CACHE)
        else:
            CACHE.write_bytes(fetch_url(URL))
    entries = json.loads(CACHE.read_text(encoding='utf-8'))

    # 2. DriverKit crypto json cache
    crypto_cache = CACHE.with_name(f'xnu-driverkit-crypto-{TAG.removeprefix("xnu-")}.json')
    if not crypto_cache.exists():
        local_crypto = LOCAL_DIR / crypto_cache.name
        if local_crypto.is_file():
            shutil.copy2(local_crypto, crypto_cache)
        else:
            crypto_url = URL.replace('/DriverKit?', '/DriverKit/crypto?')
            crypto_cache.write_bytes(fetch_url(crypto_url))
    for entry in json.loads(crypto_cache.read_text(encoding='utf-8')):
        entry['relative'] = 'crypto/' + entry['name']
        entries.append(entry)

    # 3. TrustCache json cache
    trust_tag = TRUST_TAG
    trust_cache = CACHE.with_name(f'xnu-trustcache-{TRUST_TAG.removeprefix("xnu-")}.json')
    if not trust_cache.exists():
        local_trust = LOCAL_DIR / trust_cache.name
        if local_trust.is_file():
            shutil.copy2(local_trust, trust_cache)
        else:
            url = ('https://api.github.com/repos/apple-oss-distributions/xnu/'
                   f'contents/EXTERNAL_HEADERS/TrustCache?ref={trust_tag}')
            trust_cache.write_bytes(fetch_url(url))

    # 4. Restore headers in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        restored = [entry for entry in executor.map(restore, entries) if entry]
        trust_destination = Path('.cache/xnu-work/EXTERNAL_HEADERS/TrustCache')
        def restore_trust(entry):
            return restore(entry, trust_destination, trust_tag)
        restored.extend(entry for entry in executor.map(
            restore_trust, json.loads(trust_cache.read_text(encoding='utf-8'))) if entry)

    # 5. Record restored metadata
    previous = Path('.cache/sources/xnu-restored-headers.json')
    existing = json.loads(previous.read_text(encoding='utf-8')) if previous.exists() else []
    by_name = {entry['name']: entry for entry in existing + restored}
    previous.write_text(json.dumps(list(by_name.values()), indent=2) + '\n', encoding='utf-8')
    print(f'Restored {len(restored)} omitted public headers from Apple; blob hashes verified')
