"""Synthetic704-line CPU transport proof; no artwork, GPU, or external storage."""
import argparse,base64,binascii,json,struct,sys,tempfile,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'overlay'))
from video_delivery import encode_output,extract_video

def chunk(kind,data):
 return struct.pack('>I',len(data))+kind+data+struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)
def png(frame):
 header=struct.pack('>IIBBBBB',1280,704,8,2,0,0,0)
 rows=b''.join(b'\x00'+bytes((frame%256,y%256,128))*1280 for y in range(704))
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
def main(ffmpeg=('ffmpeg',),ffprobe=('ffprobe',)):
 output={'images':[{'type':'base64','data':base64.b64encode(png(i)).decode()} for i in range(121)]}
 encoded=encode_output(output,width=1280,height=704,letterbox=False,ffmpeg=ffmpeg,ffprobe=ffprobe)
 with tempfile.TemporaryDirectory() as folder:
  result=Path(folder)/'result.json';result.write_text(json.dumps({'status':'COMPLETED','output':encoded}))
  target=extract_video(result,Path(folder)/'fixture.mp4');assert target.is_file()
 receipt={k:v for k,v in encoded['video'].items() if k!='data'}
 receipt.update(synthetic_fixture=True,gpu_used=False,full_decode_passed=True,checksum_extraction_passed=True)
 Path('hd-delivery-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--bundled-local',action='store_true');args=parser.parse_args()
 if args.bundled_local:
  media=str(Path(__file__).resolve().parents[2]/'scripts/media.mjs')
  main(('node',media,'ffmpeg'),('node',media,'ffprobe'))
 else:main()
