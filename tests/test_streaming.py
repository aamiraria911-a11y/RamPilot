import gc,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import torch
from transformers import Qwen2Config,Qwen2ForCausalLM,LlamaConfig,LlamaForCausalLM,PreTrainedTokenizerFast
from tokenizers import Tokenizer,models,pre_tokenizers
from streaming_engine import StreamingModel,TensorReader,Cancelled

class StreamingTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  torch.set_num_threads(2)
  cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
  for arch,Config,Model in [('qwen2',Qwen2Config,Qwen2ForCausalLM),('llama',LlamaConfig,LlamaForCausalLM)]:
   torch.manual_seed(42)
   config=Config(vocab_size=128,hidden_size=64,intermediate_size=128,num_hidden_layers=4,num_attention_heads=4,num_key_value_heads=2,max_position_embeddings=512,bos_token_id=1,eos_token_id=2,tie_word_embeddings=(arch=='qwen2'))
   config._attn_implementation='eager'
   model=Model(config).float().eval();folder=cls.root/arch;model.save_pretrained(folder,safe_serialization=True,max_shard_size='80KB')
   vocab={'[UNK]':0,'[BOS]':1,'[EOS]':2,'system':3,'user':4,'assistant':5,'hello':6,'helpful':7}
   vocab.update({'w'+str(i):i for i in range(8,128)})
   t=Tokenizer(models.WordLevel(vocab,unk_token='[UNK]'));t.pre_tokenizer=pre_tokenizers.Whitespace()
   t=PreTrainedTokenizerFast(tokenizer_object=t,unk_token='[UNK]',bos_token='[BOS]',eos_token='[EOS]');t.chat_template="{% for m in messages %}{{ m['role'] }} {{ m['content'] }} {% endfor %}{% if add_generation_prompt %}assistant{% endif %}";t.save_pretrained(folder)
   setattr(cls,arch+'_reference',model)
   (folder/'model.stream.json').write_text(json.dumps({'format':'rampilot-safetensors-v1','model_dir':str(folder)}))
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def model(self,arch='qwen2',**kw):return StreamingModel(self.root/arch,context=256,budget_mib=4096,threads=2,**kw)
 def test_logits_and_cached_decode_match_reference(self):
  for arch in ['qwen2','llama']:
   with self.subTest(arch=arch):
    m=self.model(arch);ref=getattr(self,arch+'_reference');ids=torch.tensor([[1,6,8,9,10]])
    with torch.inference_mode():expected=ref(ids,use_cache=False).logits[0]
    actual=m.forward(ids,all_logits=True)
    torch.testing.assert_close(actual,expected,rtol=1e-4,atol=2e-6)
    nextid=torch.tensor([[11]])
    with torch.inference_mode():expected=ref(torch.cat([ids,nextid],dim=1),use_cache=False).logits[0,-1:]
    torch.testing.assert_close(m.forward(nextid),expected,rtol=1e-4,atol=2e-6)
    self.assertEqual(m.stats['live_weight_groups'],0);self.assertEqual(m.stats['peak_live_weight_groups'],1)
    self.assertEqual(m.stats['release_checks'],10)
 def test_one_group_at_a_time_and_no_startup_weight_read(self):
  events=[];m=self.model(trace=lambda event,s:events.append((event,s['live_weight_groups'])))
  self.assertEqual(m.reader.bytes_read,0)
  m.forward(torch.tensor([[1,6,8]]))
  self.assertEqual(events,[('load',1),('release',0)]*5)
  self.assertGreater(m.reader.bytes_read,0)
  self.assertLess(m.stats['peak_live_weight_bytes'],m.reader.disk_bytes)
 def test_chunked_prefill_matches_single_pass(self):
  a=self.model();b=self.model();ids=torch.tensor([[1,6,8,9,10]])
  expected=a.forward(ids)
  b.forward(ids[:,:2],project=False);actual=b.forward(ids[:,2:])
  torch.testing.assert_close(actual,expected,rtol=1e-4,atol=2e-6)
 def test_budget_refuses_before_loading_weights(self):
  m=self.model();m.budget=m.resident_bytes()-1
  with self.assertRaises(MemoryError):m.forward(torch.tensor([[1,6]]))
  self.assertEqual(m.stats['live_weight_groups'],0)
 def test_cancel_mid_layer_releases_weights_and_kv(self):
  m=self.model()
  def stop(event,stats):
   if event=='load':m.cancel.set()
  m.trace=stop
  with self.assertRaises(Cancelled):list(m.generate([{'role':'user','content':'hello'}],3,0))
  self.assertEqual(m.stats['live_weight_groups'],0);self.assertEqual(m.cache.get_seq_length(),0)
 def test_generate_releases_cache_after_completion(self):
  m=self.model();output=list(m.generate([{'role':'user','content':'hello'}],3,0))
  self.assertTrue(output);self.assertEqual(m.cache.get_seq_length(),0);self.assertEqual(m.stats['live_weight_groups'],0)
 def test_context_rejects_oversized_request(self):
  m=self.model()
  with self.assertRaises(ValueError):list(m.generate([{'role':'user','content':'hello '*300}],4))
 def test_invalid_weight_offsets_are_rejected(self):
  folder=self.root/'corrupt';folder.mkdir(exist_ok=True)
  header=json.dumps({'model.x':{'dtype':'F32','shape':[8],'data_offsets':[0,999]}}).encode()
  import struct
  (folder/'model.safetensors').write_bytes(struct.pack('<Q',len(header))+header+b'1234')
  with self.assertRaises(ValueError):TensorReader(folder)
if __name__=='__main__':unittest.main(verbosity=2)
