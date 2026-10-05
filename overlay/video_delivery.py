"""Compact, bounded MP4 transport; no network calls or GPU dependencies."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

MAX_VIDEO_BYTES = 5_000_000  # base64 + JSON remains below an 8 MB response ceiling


def encode_output(output, expected_frames=121, fps=24, width=640, height=360,
                  ffmpeg=('ffmpeg',), ffprobe=('ffprobe',), letterbox=True):
    if output.get('error') or output.get('errors'):
        raise ValueError('Upstream generation reported errors; no partial delivery')
    images = output.get('images', [])
    if len(images) != expected_frames:
        raise ValueError('Unexpected frame count; never pad or loop missing frames')
    with tempfile.TemporaryDirectory(prefix='kael-video-') as temp:
        folder = Path(temp)
        for i, image in enumerate(images):
            if image.get('type') != 'base64':
                raise ValueError('Expected inline PNG frames; external storage disabled')
            raw = base64.b64decode(image['data'], validate=True)
            if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw) > 4_000_000:
                raise ValueError('Invalid or oversized PNG frame')
            (folder / ('frame-%05d.png' % i)).write_bytes(raw)
        target = folder / 'kael-i2v-001.mp4'
        filters = ['-vf', 'pad=iw:ih+8:0:4:black'] if letterbox else []
        subprocess.run([*ffmpeg, '-hide_banner', '-loglevel', 'error', '-n',
            '-framerate', str(fps), '-i', str(folder / 'frame-%05d.png'),
            '-frames:v', str(expected_frames), '-an', *filters, '-c:v', 'libx264',
            '-threads', '1', '-pix_fmt', 'yuv420p', '-crf', '20',
            '-movflags', '+faststart', str(target)], check=True, timeout=90)
        info = json.loads(subprocess.check_output([*ffprobe, '-v', 'error',
            '-show_entries', 'format=duration:stream=codec_name,pix_fmt,width,height,nb_frames,r_frame_rate',
            '-of', 'json', str(target)], timeout=20))
        streams = info.get('streams', [])
        if len(streams) != 1:
            raise ValueError('Expected one silent video stream')
        video = streams[0]
        if (video.get('codec_name') != 'h264' or video.get('pix_fmt') != 'yuv420p'
                or video.get('width') != width or video.get('height') != height
                or int(video.get('nb_frames', 0)) != expected_frames
                or video.get('r_frame_rate') != str(fps) + '/1'
                or abs(float(info['format']['duration']) - expected_frames/fps) > .05):
            raise ValueError('Encoded video failed technical validation')
        # Full decode, not just a container-header check.
        subprocess.run([*ffmpeg, '-v', 'error', '-i', str(target),
            '-c:v', 'rawvideo', '-f', 'null', '-'], check=True, timeout=60)
        raw = target.read_bytes()
        if len(raw) > MAX_VIDEO_BYTES:
            raise ValueError('Video exceeds bounded response size; no silent quality fallback')
        return {'video': {'filename': target.name, 'type': 'base64',
            'mime_type': 'video/mp4', 'data': base64.b64encode(raw).decode('ascii'),
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'frames': expected_frames, 'fps': fps, 'width': width, 'height': height,
            'duration_seconds': expected_frames/fps}}


def extract_video(result_path, destination):
    result = json.loads(Path(result_path).read_text())
    if result.get('status') != 'COMPLETED':
        raise ValueError('Only completed jobs can be extracted')
    video = result.get('output', {}).get('video', {})
    if video.get('type') != 'base64' or video.get('mime_type') != 'video/mp4':
        raise ValueError('Expected inline MP4 delivery')
    raw = base64.b64decode(video.get('data', ''), validate=True)
    if (not 12 <= len(raw) <= MAX_VIDEO_BYTES or raw[4:8] != b'ftyp'
            or hashlib.sha256(raw).hexdigest() != video.get('sha256')
            or len(raw) != video.get('bytes')):
        raise ValueError('MP4 checksum, size or header validation failed')
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as file:
        file.write(raw)
    return target
