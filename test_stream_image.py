import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import stream_image
from stream_image import make_layer, overlay_files, digest


class Response(io.BytesIO):
    def __init__(self, raw=b'', status=200, headers=None):
        super().__init__(raw)
        self.status = status
        self.headers = headers or {}


class FakeRegistry:
    target = 'test/proof'
    def __init__(self):
        self.config = json.dumps({'os': 'linux', 'architecture': 'amd64', 'config': {},
            'rootfs': {'diff_ids': []}, 'history': []}).encode()
        self.manifest = json.dumps({'schemaVersion': 2, 'mediaType': stream_image.OCI,
            'config': {'digest': digest(self.config), 'mediaType': 'application/vnd.oci.image.config.v1+json'},
            'layers': []}).encode()
        self.uploads = {}
        self.published = False

    def mount(self, layer):
        pass

    def request(self, path, method='GET', data=None, headers=None):
        if method == 'GET':
            return Response(self.manifest if '/manifests/' in path else self.config)
        if method == 'POST':
            loc = '/upload/' + str(len(self.uploads))
            self.uploads[loc] = bytearray()
            return Response(status=202, headers={'Location': loc})
        if method == 'PATCH':
            self.uploads[path].extend(data)
            return Response(status=202, headers={'Location': path, 'Range': '0-' + str(len(self.uploads[path]) - 1)})
        if method == 'DELETE':
            return Response(status=204)
        if '/manifests/' in path:
            self.published = True
            self.final_manifest = json.loads(data)
            return Response(status=201, headers={'Docker-Content-Digest': digest(data)})
        blob_path = path.split('?')[0]
        return Response(status=201, headers={'Docker-Content-Digest': digest(self.uploads[blob_path])})


class LayerTests(unittest.TestCase):
    def test_exact_tar_and_digests(self):
        sink = io.BytesIO()
        expected = b'large model simulation' * 10000
        diff_id = make_layer([('comfyui/models/test.bin', len(expected), 0o644, io.BytesIO(expected))], sink)
        raw = gzip.decompress(sink.getvalue())
        self.assertEqual(diff_id, 'sha256:' + hashlib.sha256(raw).hexdigest())
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            self.assertEqual(archive.extractfile('comfyui/models/test.bin').read(), expected)

    def test_private_art_is_excluded(self):
        names = [x[0] for x in overlay_files()]
        self.assertEqual(set(names), {'proof/install_runtime.py', 'proof/start.sh',
            'proof/video_delivery.py', 'proof/worker_handler.py', 'model-lock.json'})

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            make_layer([('../escape', 1, 0o644, io.BytesIO(b'x'))], io.BytesIO())

    def exercise_assembly(self, wrong_hash=False):
        model = b'pinned weights fixture' * 1000
        fake = FakeRegistry()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'overlay').mkdir()
            for name in stream_image.OVERLAY_NAMES:
                (root / 'overlay' / name).write_text('# fixture\n')
            lock = {'total_bytes': len(model), 'files': [{'filename': 'model.safetensors',
                'bytes': len(model), 'sha256': ('0' * 64 if wrong_hash else hashlib.sha256(model).hexdigest()),
                'destination': '/comfyui/models/model.safetensors', 'url': 'https://fixture.invalid/model'}]}
            (root / 'model-lock.json').write_text(json.dumps(lock))
            def source(*args, **kwargs):
                return Response(model, headers={'Content-Length': str(len(model))})
            with patch.object(stream_image, 'ROOT', root), patch.object(stream_image, 'BASE_DIGEST', digest(fake.manifest)), patch.object(stream_image.urllib.request, 'urlopen', source):
                if wrong_hash:
                    with self.assertRaises(RuntimeError):
                        stream_image.assemble(fake, 'test')
                    self.assertFalse(fake.published)
                    self.assertFalse((root / 'build-receipt.json').exists())
                else:
                    stream_image.assemble(fake, 'test')
                    self.assertTrue(fake.published)
                    self.assertEqual(len(fake.final_manifest['layers']), 2)
                    receipt = json.loads((root / 'build-receipt.json').read_text())
                    self.assertFalse(receipt['gpu_started'])
                    self.assertFalse(receipt['container_boot_verified'])

    def test_complete_manifest_assembly(self):
        self.exercise_assembly()

    def test_corrupt_model_never_publishes_manifest(self):
        self.exercise_assembly(wrong_hash=True)


if __name__ == '__main__':
    unittest.main()
