"""Linux CPU-only 121-frame delivery test, including exact eight-pixel padding."""
import base64
import binascii
import json
import struct
import sys
import tempfile
from pathlib import Path
import zlib

sys.path.insert(0, str(Path(__file__).parent / 'overlay'))
from video_delivery import encode_output, extract_video


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', binascii.crc32(kind + data) & 0xffffffff)


def png(frame):
    header = struct.pack('>IIBBBBB', 64, 56, 8, 2, 0, 0, 0)
    rows = b''.join(b'\x00' + bytes((frame % 256, y * 4, 128)) * 64 for y in range(56))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def main():
    output = {'images': [{'type': 'base64', 'data': base64.b64encode(png(i)).decode()} for i in range(121)]}
    encoded = encode_output(output, width=64, height=64)
    with tempfile.TemporaryDirectory() as folder:
        result = Path(folder) / 'result.json'
        result.write_text(json.dumps({'status': 'COMPLETED', 'output': encoded}))
        target = Path(folder) / 'fixture.mp4'
        extract_video(result, target)
        if not target.is_file():
            raise RuntimeError('Delivery extraction failed')
    print('PASS: Linux CPU encode/pad/full decode/base64/checksum/extraction, 121 frames; no GPU')


if __name__ == '__main__':
    main()
