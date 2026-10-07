"""Reject unsupported output geometry before any GPU call; retain legacy delivery."""
import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'overlay'))
from worker_handler import delivery_spec
class ContractTests(unittest.TestCase):
 def setUp(self):
  self.graph={'1':{'class_type':'Wan22ImageToVideoLatent','inputs':{'width':1280,'height':704,'length':121,'batch_size':1}}}
  self.spec={'width':1280,'height':704,'expected_frames':121,'fps':24,'letterbox':False}
 def test_legacy(self):self.assertEqual(delivery_spec({},{}),{})
 def test_supported(self):self.assertEqual(delivery_spec(self.graph,{'video_spec':self.spec}),self.spec)
 def test_six_second(self):
  self.graph['1']['inputs']['length']=145
  spec={**self.spec,'expected_frames':145}
  self.assertEqual(delivery_spec(self.graph,{'video_spec':spec}),spec)
 def test_frame_mismatch(self):
  with self.assertRaises(ValueError):delivery_spec(self.graph,{'video_spec':{**self.spec,'expected_frames':145}})
 def test_wrong_geometry(self):
  self.graph['1']['inputs']['width']=640
  with self.assertRaises(ValueError):delivery_spec(self.graph,{'video_spec':self.spec})
 def test_multiple_latents(self):
  self.graph['2']=self.graph['1']
  with self.assertRaises(ValueError):delivery_spec(self.graph,{'video_spec':self.spec})
 def test_unbounded_preset(self):
  for key,value in [('width',8192),('fps',120),('expected_frames',10000),('letterbox',0),('height','704')]:
   changed={**self.spec,key:value}
   with self.assertRaises(ValueError):delivery_spec(self.graph,{'video_spec':changed})
class BatchTests(unittest.TestCase):
 def test_approved_batch_and_rejections(self):
  import json,hashlib,base64,types
  from unittest.mock import patch,Mock
  from worker_handler import handler
  graph={'1':{'class_type':'Wan22ImageToVideoLatent','inputs':{'width':1280,'height':704,'length':145,'batch_size':1}}}
  reference=b'synthetic-reference'
  contract={'reference_name':'fixture.png','reference_sha256':hashlib.sha256(reference).hexdigest(),'video_spec':{'width':1280,'height':704,'expected_frames':145,'fps':24,'letterbox':False}}
  manifest={'approved_jobs':{'fixture':{'workflow_sha256':hashlib.sha256(json.dumps(graph,sort_keys=True).encode()).hexdigest(),'contract':contract}}}
  payload={'proof_job_id':'fixture','workflow':graph,'images':[{'name':'fixture.png','image':base64.b64encode(reference).decode()}]}
  upstream=Mock(return_value={'images':[{'type':'base64','data':'fixture'}]*145})
  encode=Mock(return_value={'video':{}})
  with patch.dict(sys.modules,{'upstream_handler':types.SimpleNamespace(handler=upstream)}),patch('worker_handler.Path.read_text',side_effect=lambda:json.dumps(manifest)),patch('worker_handler.encode_output',encode):
   handler({'input':payload})
   self.assertEqual(len(encode.call_args.args[0]['images']),144)
   self.assertEqual(encode.call_args.kwargs['expected_frames'],144)
   for change in [{'proof_job_id':'not-approved'},{'workflow':{}},{'images':[{'name':'fixture.png','image':base64.b64encode(b'wrong').decode()}]}]:
    upstream.reset_mock()
    with self.assertRaises(ValueError):handler({'input':{**payload,**change}})
    upstream.assert_not_called()
   upstream.return_value={'images':[{}]*144}
   with self.assertRaises(ValueError):handler({'input':payload})
if __name__=='__main__':unittest.main()
