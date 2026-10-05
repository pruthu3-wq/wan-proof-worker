"""GPU-free OCI assembly. Default is offline plan; publish needs explicit flag.

Reuse official Docker Hub layers with cross-repository mounts. Stream each pinned
weight into a new tar/gzip layer and registry upload without saving it to disk.
Never fall back to downloading/re-uploading the enormous base image.
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
BASE = 'runpod/worker-comfyui'
BASE_DIGEST = 'sha256:5e77b7d8ad559abcb02cca08165e400bef7372bdd9f599811c746019cb410de8'
REGISTRY = 'https://registry-1.docker.io'
OCI = 'application/vnd.oci.image.manifest.v1+json'
OVERLAY_NAMES = ('install_runtime.py', 'start.sh', 'video_delivery.py', 'worker_handler.py')


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            new.remove_header('Authorization')
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise ValueError('Insecure redirect rejected')
        return new


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


class Registry:
    def __init__(self, target):
        self.target = target
        self.opener = urllib.request.build_opener(SafeRedirect())
        self.refresh_auth()

    def refresh_auth(self):
        user, secret = os.environ['DOCKERHUB_USERNAME'], os.environ['DOCKERHUB_TOKEN']
        scopes = [('service', 'registry.docker.io'),
                  ('scope', 'repository:' + BASE + ':pull'),
                  ('scope', 'repository:' + self.target + ':pull,push')]
        req = urllib.request.Request('https://auth.docker.io/token?' + urllib.parse.urlencode(scopes))
        req.add_header('Authorization', 'Basic ' + base64.b64encode((user + ':' + secret).encode()).decode())
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.load(response)
        self.token = result['token']
        self.refresh_at = time.monotonic() + max(10, int(result.get('expires_in', 300)) - 60)

    def request(self, path, method='GET', data=None, headers=None):
        if time.monotonic() >= self.refresh_at:
            self.refresh_auth()
        url = urllib.parse.urljoin(REGISTRY, path)
        parsed = urllib.parse.urlsplit(url)
        # Never send the registry bearer token to an unexpected host.
        if parsed.scheme != 'https' or parsed.netloc != 'registry-1.docker.io':
            raise ValueError('Unexpected registry upload host')
        req = urllib.request.Request(url, data=data, method=method,
            headers={'Authorization': 'Bearer ' + self.token, **(headers or {})})
        return self.opener.open(req, timeout=180)

    def mount(self, layer):
        path = '/v2/' + self.target + '/blobs/uploads/?' + urllib.parse.urlencode(
            {'mount': layer['digest'], 'from': BASE})
        with self.request(path, 'POST', b'') as r:
            if r.status != 201:
                location = r.headers.get('Location')
                if location:
                    with self.request(location, 'DELETE'):
                        pass
                raise RuntimeError('Base blob mount unavailable; stopped without downloading base')


class Upload:
    """Small bounded chunks; HTTP status/offset checked on every write."""
    def __init__(self, registry):
        self.registry = registry
        with registry.request('/v2/' + registry.target + '/blobs/uploads/', 'POST', b'') as r:
            if r.status != 202:
                raise RuntimeError('Upload not accepted')
            self.location = r.headers['Location']
        self.h = hashlib.sha256()
        self.size = 0
        self.pending = bytearray()
        self.finished = False

    def write(self, raw):
        self.h.update(raw)
        self.size += len(raw)
        self.pending.extend(raw)
        if len(self.pending) >= 8 * 1024 * 1024:
            self.flush()
        return len(raw)

    def flush(self):
        if self.pending:
            payload = bytes(self.pending)
            with self.registry.request(self.location, 'PATCH', payload,
                    {'Content-Type': 'application/octet-stream'}) as r:
                if r.status != 202:
                    raise RuntimeError('Chunk rejected')
                self.location = r.headers['Location']
                returned = r.headers.get('Range', '').removeprefix('bytes=')
                if returned != '0-' + str(self.size - 1):
                    raise RuntimeError('Registry upload offset mismatch')
            self.pending.clear()

    def finish(self):
        self.flush()
        dg = 'sha256:' + self.h.hexdigest()
        sep = '&' if '?' in self.location else '?'
        with self.registry.request(self.location + sep + 'digest=' + dg, 'PUT', b'') as r:
            if r.status != 201 or r.headers.get('Docker-Content-Digest') != dg:
                raise RuntimeError('Registry digest confirmation failed')
        self.finished = True
        return {'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip',
                'digest': dg, 'size': self.size}

    def cancel(self):
        if not self.finished:
            try:
                with self.registry.request(self.location, 'DELETE'):
                    pass
            except Exception:
                pass


class HashWriter:
    def __init__(self, sink):
        self.h = hashlib.sha256()
        self.sink = sink

    def write(self, raw):
        self.h.update(raw)
        return self.sink.write(raw)

    def flush(self):
        self.sink.flush()


class ModelReader:
    def __init__(self, response):
        self.response = response
        self.h = hashlib.sha256()
        self.size = 0

    def read(self, size):
        raw = self.response.read(size)
        self.h.update(raw)
        self.size += len(raw)
        return raw


def make_layer(files, sink):
    """files is (archive name, size, mode, binary reader) tuples."""
    gz = gzip.GzipFile(fileobj=sink, mode='wb', mtime=0)
    uncompressed = HashWriter(gz)
    with tarfile.open(fileobj=uncompressed, mode='w|') as archive:
        for name, size, mode, reader in files:
            if name.startswith('/') or '..' in Path(name).parts:
                raise ValueError('Unsafe layer path')
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = size, mode, 0
            entry.uid = entry.gid = 0
            archive.addfile(entry, reader)
    gz.close()
    return 'sha256:' + uncompressed.h.hexdigest()


def overlay_files():
    result = []
    # Explicit allowlist: Python caches and unrelated files must never be baked.
    for name in OVERLAY_NAMES:
        p = ROOT / 'overlay' / name
        raw = p.read_bytes()
        result.append(('proof/' + p.name, len(raw), 0o755 if p.suffix == '.sh' else 0o644, io.BytesIO(raw)))
    raw = (ROOT / 'model-lock.json').read_bytes()
    result.append(('model-lock.json', len(raw), 0o644, io.BytesIO(raw)))
    return result


def assemble(registry, tag):
    with registry.request('/v2/' + BASE + '/manifests/' + BASE_DIGEST,
                          headers={'Accept': OCI}) as r:
        raw = r.read()
    if digest(raw) != BASE_DIGEST:
        raise RuntimeError('Base manifest checksum mismatch')
    manifest = json.loads(raw)
    with registry.request('/v2/' + BASE + '/blobs/' + manifest['config']['digest']) as r:
        raw = r.read()
    if digest(raw) != manifest['config']['digest']:
        raise RuntimeError('Base configuration checksum mismatch')
    config = json.loads(raw)
    if (config['os'], config['architecture']) != ('linux', 'amd64'):
        raise RuntimeError('Wrong base platform')
    for layer in manifest['layers']:
        registry.mount(layer)
    lock = json.loads((ROOT / 'model-lock.json').read_text())
    diff_ids = []
    for model in lock['files']:
        upload = Upload(registry)
        try:
            with urllib.request.urlopen(model['url'], timeout=180) as response:
                if int(response.headers['Content-Length']) != model['bytes']:
                    raise RuntimeError('Model content length changed')
                reader = ModelReader(response)
                diff_id = make_layer([(model['destination'].lstrip('/'), model['bytes'], 0o644, reader)], upload)
                if reader.size != model['bytes'] or reader.h.hexdigest() != model['sha256']:
                    raise RuntimeError('Pinned model integrity failure; manifest will not be published')
            manifest['layers'].append(upload.finish())
            diff_ids.append(diff_id)
            print('Verified and uploaded:', model['filename'], flush=True)
        finally:
            upload.cancel()
    upload = Upload(registry)
    try:
        diff_ids.append(make_layer(overlay_files(), upload))
        manifest['layers'].append(upload.finish())
    finally:
        upload.cancel()
    config['rootfs']['diff_ids'].extend(diff_ids)
    config.setdefault('history', []).extend([
        {'created_by': 'Pinned checksum-verified proof layer'} for _ in diff_ids])
    cfg = config['config']
    cfg['Cmd'] = ['/proof/start.sh']
    cfg['Env'] = [e for e in cfg.get('Env', []) if e.split('=', 1)[0] not in
                  ('SERVE_API_LOCALLY', 'REFRESH_WORKER', 'COMFY_LOG_LEVEL')]
    cfg['Env'].extend(['SERVE_API_LOCALLY=false', 'REFRESH_WORKER=false', 'COMFY_LOG_LEVEL=INFO'])
    raw = json.dumps(config, separators=(',', ':')).encode()
    upload = Upload(registry)
    try:
        upload.write(raw)
        desc = upload.finish()
    finally:
        upload.cancel()
    desc['mediaType'] = manifest['config']['mediaType']
    manifest['config'] = desc
    raw = json.dumps(manifest, separators=(',', ':')).encode()
    with registry.request('/v2/' + registry.target + '/manifests/' + tag, 'PUT', raw,
                          {'Content-Type': manifest['mediaType']}) as r:
        if r.status != 201 or r.headers.get('Docker-Content-Digest') != digest(raw):
            raise RuntimeError('Manifest publish failed')
    receipt = {'image': registry.target + '@' + digest(raw), 'platform': 'linux/amd64',
               'model_bytes': lock['total_bytes'], 'published_at_unix': int(time.time()),
               'compressed_image_bytes': sum(layer['size'] for layer in manifest['layers']),
               'full_model_checksums_verified': True,
               'base_layers_reused': True,
               'gpu_started': False, 'container_boot_verified': False}
    (ROOT / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--publish', action='store_true')
    p.add_argument('--repository')
    p.add_argument('--tag', default='proof-v1')
    args = p.parse_args()
    if not args.publish:
        sink = io.BytesIO()
        diff_id = make_layer(overlay_files(), sink)
        print(json.dumps({'status': 'OFFLINE_PREPARATION_ONLY', 'overlay_bytes': len(sink.getvalue()),
            'overlay_diff_id': diff_id, 'model_bytes': json.loads((ROOT/'model-lock.json').read_text())['total_bytes'],
            'base_layers_downloaded': False, 'gpu_started': False}, indent=2))
        return
    if not args.repository or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9_.-]*', args.repository):
        p.error('Explicit Docker Hub namespace/repository required')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', args.tag):
        p.error('Invalid tag')
    assemble(Registry(args.repository), args.tag)


if __name__ == '__main__':
    main()
