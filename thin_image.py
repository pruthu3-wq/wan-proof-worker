"""Small technical-only update atop existing model-equipped image. No model downloads."""
import argparse,copy,gzip,hashlib,io,json,tarfile
from pathlib import Path
import stream_image as stream
ROOT=Path(__file__).resolve().parent
REPO='pruthu3/wan-proof-worker'
BASE_DIGEST='sha256:8c592610996ef439a02383271de9cd937dc3b47e8c1bd396f84e1d4fcbef30f1'
TAG='delivery-704-six-second-v3'

def layer_files():
    raw=(ROOT/'overlay/worker_handler.py').read_bytes()
    return [('proof/worker_handler.py',len(raw),0o644,io.BytesIO(raw))]

def main(publish=False):
    if not publish:
        sink=io.BytesIO();diff=stream.make_layer(layer_files(),sink)
        print(json.dumps({'offline_only':True,'technical_layer_bytes':len(sink.getvalue()),
            'diff_id':diff,'model_download_bytes':0,'gpu_started':False}));return
    stream.BASE=REPO
    registry=stream.Registry(REPO)
    def read(path,limit=150000):
        with registry.request(path,headers={'Accept':stream.OCI}) as response:raw=response.read(limit+1)
        if len(raw)>limit:raise ValueError('Unexpected metadata size')
        return raw
    base_raw=read('/v2/'+REPO+'/manifests/'+BASE_DIGEST)
    if stream.digest(base_raw)!=BASE_DIGEST:raise ValueError('Immutable base mismatch')
    base=json.loads(base_raw);manifest=copy.deepcopy(base)
    config_raw=read('/v2/'+REPO+'/blobs/'+base['config']['digest'])
    if stream.digest(config_raw)!=base['config']['digest']:raise ValueError('Base config hash mismatch')
    config=json.loads(config_raw)
    if (config['os'],config['architecture'],config['config']['Cmd'])!=('linux','amd64',['/proof/start.sh']):
        raise ValueError('Unexpected base startup/platform')
    # Same registry repository: existing model layers are referenced unchanged, never reuploaded.
    upload=stream.Upload(registry)
    try:
        diff=stream.make_layer(layer_files(),upload);manifest['layers'].append(upload.finish())
    finally:upload.cancel()
    config['rootfs']['diff_ids'].append(diff)
    config.setdefault('history',[]).append({'created_by':'Bounded704deliverywrapper; models reused'})
    raw=json.dumps(config,separators=(',',':')).encode();upload=stream.Upload(registry)
    try:upload.write(raw);desc=upload.finish()
    finally:upload.cancel()
    desc['mediaType']=base['config']['mediaType'];manifest['config']=desc
    raw=json.dumps(manifest,separators=(',',':')).encode();wanted=stream.digest(raw)
    with registry.request('/v2/'+REPO+'/manifests/'+TAG,'PUT',raw,{'Content-Type':manifest['mediaType']}) as response:
        if response.status!=201 or response.headers.get('Docker-Content-Digest')!=wanted:raise ValueError('Publish failed')
    actual=read('/v2/'+REPO+'/manifests/'+wanted)
    if stream.digest(actual)!=wanted:raise ValueError('Manifest readback mismatch')
    decoded=json.loads(actual)
    if decoded['layers'][:-1]!=base['layers']:raise ValueError('Base layers changed')
    raw=read('/v2/'+REPO+'/blobs/'+decoded['layers'][-1]['digest'])
    if stream.digest(raw)!=decoded['layers'][-1]['digest']:raise ValueError('Technical layer mismatch')
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw)),mode='r:') as archive:
        if archive.getnames()!=['proof/worker_handler.py']:raise ValueError('Unexpected uploaded file')
        if archive.extractfile('proof/worker_handler.py').read()!=(ROOT/'overlay/worker_handler.py').read_bytes():
            raise ValueError('Published wrapper content mismatch')
    receipt={'image':REPO+'@'+wanted,'base_image':REPO+'@'+BASE_DIGEST,'platform':'linux/amd64',
        'base_layers_reused':True,'model_download_bytes':0,'new_layer_bytes':decoded['layers'][-1]['size'],
        'technical_only_allowlist_verified':True,'metadata_and_layer_readback_verified':True,
        'container_startup_tested':False,'gpu_started':False}
    (ROOT/'thin-build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true')
    main(parser.parse_args().publish)
