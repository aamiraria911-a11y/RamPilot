import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mobile'))
import numpy as np
import torch
from transformers import Qwen2Config,Qwen2ForCausalLM,AutoTokenizer
from numpy_streamer import NumpyStreamingModel,QwenTokenizer,Stopped
class MobileTests(unittest.TestCase):
 def test_numpy_logits_and_cached_decode_match_pytorch(self):
  with tempfile.TemporaryDirectory() as d:
   torch.manual_seed(12);c=Qwen2Config(vocab_size=128,hidden_size=64,intermediate_size=128,num_hidden_layers=3,num_attention_heads=4,num_key_value_heads=2,max_position_embeddings=256,tie_word_embeddings=True);c._attn_implementation='eager';ref=Qwen2ForCausalLM(c).float().eval();ref.save_pretrained(d,safe_serialization=True,max_shard_size='80KB')
   m=NumpyStreamingModel(d,256,2048,tokenizer=False);ids=[1,6,8,10]
   with torch.inference_mode():expected=ref(torch.tensor([ids]),use_cache=False).logits[0,-1].numpy()
   np.testing.assert_allclose(m.forward(ids),expected,rtol=1e-4,atol=2e-6)
   with torch.inference_mode():expected=ref(torch.tensor([ids+[11]]),use_cache=False).logits[0,-1].numpy()
   np.testing.assert_allclose(m.forward([11]),expected,rtol=1e-4,atol=2e-6)
   self.assertEqual(m.stats['peak_live_weight_groups'],1);self.assertEqual(m.stats['live_weight_groups'],0);self.assertEqual(m.stats['released_groups'],6)
 def test_qwen_tokenizer_matches_official(self):
  folder=Path(__file__).parent/'real-model';a=QwenTokenizer(folder);b=AutoTokenizer.from_pretrained(folder,local_files_only=True)
  for text in ['Hello, world!','سلام امیر، خوبی؟','مرحبا بالعالم','print("hello")\n    x = 12','Emoji 😄 and café','1234567890','<|im_start|>user\nhello<|im_end|>\n']:
   self.assertEqual(a.encode(text),b.encode(text,add_special_tokens=False));self.assertEqual(a.decode(a.encode(text)),b.decode(b.encode(text),skip_special_tokens=True,clean_up_tokenization_spaces=False))
  messages=[{'role':'system','content':'You are helpful.'},{'role':'user','content':'Hi'}]
  self.assertEqual(a.chat(messages),b.apply_chat_template(messages,tokenize=False,add_generation_prompt=True))
if __name__=='__main__':unittest.main(verbosity=2)
