"""Single fixed Kael proof job; preserves the official ComfyUI handler/startup."""
import hashlib
import base64
import json
from pathlib import Path

from video_delivery import encode_output


def handler(job):
    import upstream_handler
    approved = json.loads(Path('/kael-workflow.json').read_text())
    if job.get('input', {}).get('workflow') != approved:
        raise ValueError('This worker accepts only the fixed first-test workflow')
    contract = json.loads(Path('/proof-contract.json').read_text())
    images = job['input'].get('images', [])
    if len(images) != 1 or images[0].get('name') != contract['reference_name']:
        raise ValueError('This worker requires the single approved reference')
    encoded = images[0].get('image', '').removeprefix('data:image/png;base64,')
    if hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest() != contract['reference_sha256']:
        raise ValueError('Reference checksum mismatch')
    output = upstream_handler.handler(job)
    delivered = encode_output(output)
    delivered['workflow_sha256'] = hashlib.sha256(
        json.dumps(approved, sort_keys=True).encode()).hexdigest()
    return delivered


if __name__ == '__main__':
    import runpod
    runpod.serverless.start({'handler': handler})
