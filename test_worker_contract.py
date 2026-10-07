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
if __name__=='__main__':unittest.main()
