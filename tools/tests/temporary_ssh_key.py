"""Board-side test helper: add/remove one uniquely tagged acceptance public key."""
import json
import os
from pathlib import Path
import sys

action, public_file = sys.argv[1:]
key = Path(public_file).read_text().strip()
if not key.startswith('ssh-rsa ') or not key.split()[-1].startswith('av-dev-acceptance-'):
    raise SystemExit('Not an acceptance public key')
folder = Path.home() / '.ssh'
path = folder / 'authorized_keys'
if action == 'add':
    folder.mkdir(mode=0o700, exist_ok=True)
    original = path.read_bytes() if path.exists() else b''
    if key.encode() not in original.splitlines():
        with path.open('ab') as file:
            file.write((b'\n' if original and not original.endswith(b'\n') else b'') + key.encode() + b'\n')
    os.chmod(path, 0o600)
    print(json.dumps({'added': True}))
elif action == 'remove':
    original = path.read_bytes() if path.exists() else b''
    lines = original.splitlines(keepends=True)
    filtered = [line for line in lines if line.strip() != key.encode()]
    if filtered != lines:
        temporary = path.with_suffix('.av-dev-cleanup')
        temporary.write_bytes(b''.join(filtered))
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    print(json.dumps({'removed': key.encode() not in path.read_bytes().splitlines()}))
else:
    raise SystemExit('add/remove only')
