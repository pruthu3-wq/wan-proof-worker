"""Read back public image metadata and small technical layer; never pull weights."""
import gzip
import io
import json
from pathlib import Path
import tarfile
import urllib.parse
import urllib.request

from stream_image import BASE, BASE_DIGEST, OCI, OVERLAY_NAMES, REGISTRY, SafeRedirect, digest


def inspect():
    root = Path(__file__).resolve().parent
    receipt = json.loads((root / 'build-receipt.json').read_text())
    repo, wanted = receipt['image'].split('@')
    params = [('service', 'registry.docker.io'), ('scope', 'repository:' + repo + ':pull'),
              ('scope', 'repository:' + BASE + ':pull')]
    with urllib.request.urlopen('https://auth.docker.io/token?' + urllib.parse.urlencode(params), timeout=60) as r:
        token = json.load(r)['token']
    opener = urllib.request.build_opener(SafeRedirect())

    def read(path, limit=100_000):
        req = urllib.request.Request(REGISTRY + path,
            headers={'Authorization': 'Bearer ' + token, 'Accept': OCI})
        with opener.open(req, timeout=180) as r:
            raw = r.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Read-back unexpectedly large')
        return raw

    raw = read('/v2/' + repo + '/manifests/' + wanted)
    if digest(raw) != wanted:
        raise ValueError('Published manifest digest mismatch')
    manifest = json.loads(raw)
    raw = read('/v2/' + BASE + '/manifests/' + BASE_DIGEST)
    if digest(raw) != BASE_DIGEST:
        raise ValueError('Base digest mismatch')
    base = json.loads(raw)
    n = len(base['layers'])
    if manifest['layers'][:n] != base['layers'] or len(manifest['layers']) != n + 4:
        raise ValueError('Unexpected base or additional image layers')
    raw = read('/v2/' + repo + '/blobs/' + manifest['config']['digest'])
    if digest(raw) != manifest['config']['digest']:
        raise ValueError('Published config digest mismatch')
    config = json.loads(raw)
    if (config['os'], config['architecture'], config['config']['Cmd']) != ('linux', 'amd64', ['/proof/start.sh']):
        raise ValueError('Unexpected platform or startup command')
    env = config['config'].get('Env', [])
    if not all(x in env for x in ('SERVE_API_LOCALLY=false', 'REFRESH_WORKER=false')):
        raise ValueError('Worker control environment missing')
    if any(x.startswith(('PROOF_WORKFLOW_B64=', 'PROOF_CONTRACT_B64=', 'RUNPOD_API_KEY=', 'DOCKERHUB_TOKEN=')) for x in env):
        raise ValueError('Private runtime configuration accidentally baked')
    overlay = manifest['layers'][-1]
    raw = read('/v2/' + repo + '/blobs/' + overlay['digest'])
    if digest(raw) != overlay['digest']:
        raise ValueError('Technical overlay checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw))) as archive:
        names = archive.getnames()
        if set(names) != {'proof/' + x for x in OVERLAY_NAMES} | {'model-lock.json'}:
            raise ValueError('Unexpected files in public overlay')
    result = {'image': receipt['image'], 'manifest_digest_verified': True,
        'configuration_digest_verified': True, 'linux_amd64_verified': True,
        'official_base_layers_verified': True, 'technical_overlay_allowlist_verified': True,
        'private_environment_not_baked': True,
        'compressed_image_bytes': sum(x['size'] for x in manifest['layers']),
        'model_layers_downloaded_for_inspection': False,
        'full_container_startup_tested': False, 'gpu_tested': False}
    (root / 'inspection-receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    inspect()
