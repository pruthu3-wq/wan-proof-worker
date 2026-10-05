"""Install the fixed proof contract privately at worker boot; never download models."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil


def install():
    for key, path in [('PROOF_WORKFLOW_B64', '/kael-workflow.json'),
                      ('PROOF_CONTRACT_B64', '/proof-contract.json')]:
        raw = base64.b64decode(os.environ[key], validate=True)
        if len(raw) > 100_000:
            raise ValueError('Proof configuration too large')
        json.loads(raw)
        Path(path).write_bytes(raw)
        Path(path).chmod(0o600)
    lock = json.loads(Path('/model-lock.json').read_text())
    for item in lock['files']:
        p = Path(item['destination'])
        if p.stat().st_size != item['bytes']:
            raise ValueError('Model size mismatch')
        # The build already hashes complete transfers. Read again on the worker
        # before loading to detect corruption; include this in startup allowance.
        h = hashlib.sha256()
        with p.open('rb') as f:
            while chunk := f.read(8 * 1024 * 1024):
                h.update(chunk)
        if h.hexdigest() != item['sha256']:
            raise ValueError('Model checksum mismatch')
    shutil.copyfile('/handler.py', '/upstream_handler.py')
    shutil.copyfile('/proof/worker_handler.py', '/handler.py')
    shutil.copyfile('/proof/video_delivery.py', '/video_delivery.py')


if __name__ == '__main__':
    install()
