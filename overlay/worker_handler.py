"""Single privately configured, fixed proof job; preserves the official ComfyUI handler/startup."""
import hashlib
import base64
import json
from pathlib import Path

from video_delivery import encode_output


def delivery_spec(approved, contract):
    spec = contract.get('video_spec', {})
    if not spec:
        return {}  # Preserve the already-proven 640x360 transport.
    expected = {'width': 1280, 'height': 704, 'expected_frames': 121,
                'fps': 24, 'letterbox': False}
    if (not isinstance(spec, dict) or spec != expected
            or any(type(spec[k]) is not type(v) for k, v in expected.items())):
        raise ValueError('Unsupported delivery preset')
    latents = [n['inputs'] for n in approved.values()
               if n.get('class_type') == 'Wan22ImageToVideoLatent']
    if (len(latents) != 1 or any(latents[0].get(k) != v for k,v in
            [('width',1280),('height',704),('length',121),('batch_size',1)])):
        raise ValueError('Workflow/delivery geometry mismatch')
    return spec


def handler(job):
    import upstream_handler
    approved = json.loads(Path('/kael-workflow.json').read_text())
    if job.get('input', {}).get('workflow') != approved:
        raise ValueError('This worker accepts only the fixed first-test workflow')
    contract = json.loads(Path('/proof-contract.json').read_text())
    spec = delivery_spec(approved, contract)
    images = job['input'].get('images', [])
    if len(images) != 1 or images[0].get('name') != contract['reference_name']:
        raise ValueError('This worker requires the single approved reference')
    encoded = images[0].get('image', '').removeprefix('data:image/png;base64,')
    if hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest() != contract['reference_sha256']:
        raise ValueError('Reference checksum mismatch')
    output = upstream_handler.handler(job)
    delivered = encode_output(output, **spec)
    delivered['workflow_sha256'] = hashlib.sha256(
        json.dumps(approved, sort_keys=True).encode()).hexdigest()
    return delivered


if __name__ == '__main__':
    import runpod
    runpod.serverless.start({'handler': handler})
