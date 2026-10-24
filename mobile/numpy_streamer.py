"""Local Qwen2/2.5 layer streaming using NumPy, including local BPE.
No PyTorch, PC server, model mmap or model-wide weight allocation is used.
"""
import gc,json,math,os,struct,threading,weakref,sys,time
from pathlib import Path
import numpy as np
import regex

class Stopped(Exception):pass

class Weights:
 def __init__(self,folder):
  self.folder=Path(folder);self.entries={};self.bytes_read=0
  index=self.folder/'model.safetensors.index.json'
  names=sorted(set(json.loads(index.read_text())['weight_map'].values())) if index.exists() else [p.name for p in self.folder.glob('model*.safetensors')]
  if not names:raise ValueError('No SafeTensors model files found')
  for name in names:
   if Path(name).name!=name:raise ValueError('Invalid shard path')
   p=self.folder/name;size=p.stat().st_size
   with p.open('rb',buffering=0) as f:
    raw=f.read(8)
    if len(raw)!=8:raise ValueError('Truncated SafeTensors file')
    length=struct.unpack('<Q',raw)[0]
    if not 2<=length<=min(size-8,32*1024*1024):raise ValueError('Invalid header')
    header=json.loads(f.read(length))
   intervals=[]
   for k,v in header.items():
    if k=='__metadata__':continue
    dtype=v['dtype'];shape=tuple(v['shape']);a,b=v['data_offsets']
    if dtype not in ('F32','F16','BF16') or not shape or any(type(d)!=int or d<=0 for d in shape):raise ValueError('Unsupported tensor type or shape')
    width=4 if dtype=='F32' else 2
    if not 0<=a<b<=size-8-length or b-a!=math.prod(shape)*width:raise ValueError('Invalid tensor offsets')
    if k in self.entries:raise ValueError('Duplicate tensor')
    self.entries[k]=(p,8+length+a,shape,dtype);intervals.append((a,b))
   intervals.sort()
   if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])):raise ValueError('Overlapping tensors')
  self.total=sum(p.stat().st_size for p in {e[0] for e in self.entries.values()})
 def read(self,key,row_start=None,row_end=None):
  p,offset,shape,dtype=self.entries[key];width=4 if dtype=='F32' else 2
  if row_start is not None:
   if len(shape)!=2 or not 0<=row_start<row_end<=shape[0]:raise ValueError('Invalid row range')
   offset+=row_start*shape[1]*width;shape=(row_end-row_start,shape[1])
  data=bytearray(math.prod(shape)*width)
  with p.open('rb',buffering=0) as f:
   f.seek(offset);view=memoryview(data);done=0
   while done<len(data):
    n=f.readinto(view[done:])
    if not n:raise IOError('Model file truncated')
    done+=n
  self.bytes_read+=len(data)
  if dtype=='BF16':return (np.frombuffer(data,dtype='<u2').astype(np.uint32)<<16).view(np.float32).reshape(shape)
  return np.frombuffer(data,dtype='<f4' if dtype=='F32' else '<f2').astype(np.float32,copy=False).reshape(shape)

class QwenTokenizer:
 def __init__(self,folder):
  data=json.loads((Path(folder)/'tokenizer.json').read_text('utf-8'))
  self.vocab=data['model']['vocab'];self.inverse={v:k for k,v in self.vocab.items()}
  merges=data['model']['merges'];self.ranks={tuple(m.split(' ')) if isinstance(m,str) else tuple(m):i for i,m in enumerate(merges)}
  added=data.get('added_tokens',[]);self.special={x['content']:x['id'] for x in added};self.special_ids={x['id'] for x in added if x.get('special')}
  self.inverse.update({x['id']:x['content'] for x in added})
  nums=list(range(33,127))+list(range(161,173))+list(range(174,256));chars=list(nums);n=0
  for b in range(256):
   if b not in nums:nums.append(b);chars.append(256+n);n+=1
  self.byte_to_char=dict(zip(nums,map(chr,chars)));self.char_to_byte={c:b for b,c in self.byte_to_char.items()}
  def pattern(node):
   if node.get('type')=='Split':return node['pattern'].get('Regex')
   for child in node.get('pretokenizers',[]):
    p=pattern(child)
    if p:return p
  p=pattern(data['pre_tokenizer'])
  if not p:raise ValueError('Unsupported tokenizer pre-tokenizer')
  self.pattern=regex.compile(p);self.split_special=regex.compile('('+'|'.join(regex.escape(s) for s in sorted(self.special,key=len,reverse=True))+')')
  self.cache={}
 def encode(self,text):
  result=[]
  for part in self.split_special.split(text):
   if not part:continue
   if part in self.special:result.append(self.special[part]);continue
   for piece in self.pattern.findall(part):
    encoded=''.join(self.byte_to_char[b] for b in piece.encode('utf-8'))
    cached=self.cache.get(encoded)
    if cached is None:
     tokens=list(encoded)
     while len(tokens)>1:
      pairs=[(self.ranks.get((tokens[i],tokens[i+1]),10**12),i) for i in range(len(tokens)-1)]
      rank,i=min(pairs)
      if rank==10**12:break
      tokens[i:i+2]=[tokens[i]+tokens[i+1]]
     cached=[self.vocab[t] for t in tokens]
     if len(self.cache)>20000:self.cache.clear()
     self.cache[encoded]=cached
    result.extend(cached)
  return result
 def decode(self,ids):
  out=bytearray()
  for i in ids:
   if i in self.special_ids:continue
   for c in self.inverse[i]:
    if c not in self.char_to_byte:out.extend(c.encode('utf-8'))
    else:out.append(self.char_to_byte[c])
  return out.decode('utf-8',errors='replace')
 def chat(self,messages):
  # The standard Qwen2.5 text chat template, without tools or multimodal input.
  if not messages or messages[0]['role']!='system':messages=[{'role':'system','content':'You are Qwen, created by Alibaba Cloud. You are a helpful assistant.'}]+list(messages)
  if any(m['role'] not in ('system','user','assistant') or not isinstance(m['content'],str) for m in messages):raise ValueError('Unsupported chat message')
  return ''.join('<|im_start|>'+m['role']+'\n'+m['content']+'<|im_end|>\n' for m in messages)+'<|im_start|>assistant\n'

class NumpyStreamingModel:
 def __init__(self,folder,context=512,budget_mib=1024,tokenizer=True,progress=None):
  self.folder=Path(folder);self.config=json.loads((self.folder/'config.json').read_text());c=self.config
  if c.get('model_type')!='qwen2' or c.get('quantization_config') or c.get('use_sliding_window'):raise ValueError('This engine supports standard dense Qwen2/Qwen2.5 SafeTensors models')
  self.hidden=c['hidden_size'];self.layers=c['num_hidden_layers'];self.heads=c['num_attention_heads'];self.kvheads=c['num_key_value_heads'];self.dim=self.hidden//self.heads
  if self.hidden%self.heads or self.heads%self.kvheads:raise ValueError('Invalid attention dimensions')
  if c.get('rope_scaling'):raise ValueError('This engine uses standard RoPE only')
  self.context=min(max(64,int(context)),2048,c['max_position_embeddings']);self.budget=max(256,int(budget_mib))*1048576
  self.reader=Weights(folder);self.tokenizer=QwenTokenizer(folder) if tokenizer else None;self.cancel=threading.Event();self.progress=progress or (lambda s:None)
  self.stats={'backend':'numpy-layer-streaming','current_group':'idle','live_weight_groups':0,'peak_live_weight_groups':0,'released_groups':0,'peak_live_weight_bytes':0,'layer_count':self.layers}
  self.cache=[None]*self.layers;self.position=0
  self.groups=[sorted(k for k in self.reader.entries if k.startswith('model.layers.'+str(i)+'.')) for i in range(self.layers)]
  if any(not g for g in self.groups):raise ValueError('Missing decoder layer')
  self.head='lm_head.weight' if 'lm_head.weight' in self.reader.entries else 'model.embed_tokens.weight'
  if self.head.startswith('model.embed') and not c.get('tie_word_embeddings',False):raise ValueError('Missing output head')
  largest=max(sum(math.prod(self.reader.entries[k][2])*4 for k in keys) for keys in self.groups)
  self.check(largest*2+self.context*self.layers*self.kvheads*self.dim*8+32*1048576)
 def rss(self):
  try:
   for line in Path('/proc/self/status').read_text().splitlines():
    if line.startswith('VmRSS:'):return int(line.split()[1])*1024
  except OSError:pass
  try:
   import resource
   value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
   return int(value) if sys.platform=='darwin' else int(value)*1024
  except (ImportError,OSError):return 0
 def check(self,extra=0):
  if self.rss()+extra>self.budget:raise MemoryError('This layer exceeds the selected memory budget. Choose a smaller model or context.')
 def metrics(self):
  return dict(self.stats,rss_bytes=self.rss(),bytes_read=self.reader.bytes_read,budget_bytes=self.budget,context=self.context,rss_kind='peak' if sys.platform=='darwin' else 'current')
 def checkpoint(self):
  if self.cancel.is_set():raise Stopped('Stopped')
  self.progress(self.metrics())
 def norm(self,x,w):return x/np.sqrt(np.mean(x*x,axis=-1,keepdims=True)+self.config['rms_norm_eps'])*w
 def linear(self,x,weights,name):
  y=x@weights[name+'.weight'].T
  if name+'.bias' in weights:y+=weights[name+'.bias']
  return y
 def forward(self,ids,project=True):
  ids=list(ids);self.checkpoint()
  if not 1<=len(ids)<=16 or self.position+len(ids)>self.context:raise ValueError('Context or input chunk limit reached')
  self.check(len(ids)*self.hidden*4+8*1048576)
  hidden=np.stack([self.reader.read('model.embed_tokens.weight',i,i+1)[0] for i in ids])
  positions=np.arange(self.position,self.position+len(ids),dtype=np.float32)
  freqs=positions[:,None]/(self.config.get('rope_theta',10000.0)**(np.arange(0,self.dim,2,dtype=np.float32)/self.dim))[None,:]
  angles=np.concatenate([freqs,freqs],axis=-1)[:,None,:];cos=np.cos(angles);sin=np.sin(angles)
  def rotate(x):return np.concatenate([-x[...,self.dim//2:],x[...,:self.dim//2]],axis=-1)
  for i,keys in enumerate(self.groups):
   self.checkpoint();needed=sum(math.prod(self.reader.entries[k][2])*4 for k in keys);self.check(needed*2+16*1048576)
   if self.stats['live_weight_groups']:raise RuntimeError('A previous block is still live')
   self.stats.update(current_group='layer '+str(i+1)+'/'+str(self.layers),live_weight_groups=1)
   self.stats['peak_live_weight_groups']=1;self.stats['peak_live_weight_bytes']=max(needed,self.stats['peak_live_weight_bytes'])
   weights={};refs=[]
   try:
    prefix='model.layers.'+str(i)+'.';weights.update({k[len(prefix):]:self.reader.read(k) for k in keys});refs=[weakref.ref(w) for w in weights.values()]
    self.checkpoint();residual=hidden;x=self.norm(hidden,weights['input_layernorm.weight'])
    q=self.linear(x,weights,'self_attn.q_proj').reshape(len(ids),self.heads,self.dim);k=self.linear(x,weights,'self_attn.k_proj').reshape(len(ids),self.kvheads,self.dim);v=self.linear(x,weights,'self_attn.v_proj').reshape(len(ids),self.kvheads,self.dim)
    q=q*cos+rotate(q)*sin;k=k*cos+rotate(k)*sin
    if self.cache[i] is not None:k=np.concatenate([self.cache[i][0],k],axis=0);v=np.concatenate([self.cache[i][1],v],axis=0)
    self.cache[i]=(k,v);kr=np.repeat(k,self.heads//self.kvheads,axis=1);vr=np.repeat(v,self.heads//self.kvheads,axis=1)
    scores=np.matmul(q.transpose(1,0,2),kr.transpose(1,2,0))/np.float32(math.sqrt(self.dim))
    scores=np.where(np.arange(len(k))[None,None,:]>positions[None,:,None],np.float32(-1e30),scores);scores-=scores.max(axis=-1,keepdims=True);scores=np.exp(scores);scores/=scores.sum(axis=-1,keepdims=True)
    attention=np.matmul(scores,vr.transpose(1,0,2)).transpose(1,0,2).reshape(len(ids),self.hidden)
    hidden=residual+self.linear(attention,weights,'self_attn.o_proj');x=self.norm(hidden,weights['post_attention_layernorm.weight'])
    gate=self.linear(x,weights,'mlp.gate_proj');up=self.linear(x,weights,'mlp.up_proj');gate=gate/(1+np.exp(-np.clip(gate,-80,80)))
    hidden=hidden+self.linear(gate*up,weights,'mlp.down_proj')
   finally:
    weights.clear();gc.collect()
    if any(r() is not None for r in refs):raise RuntimeError('Block weight release failed')
    self.stats.update(current_group='idle',live_weight_groups=0);self.stats['released_groups']+=1
  self.position+=len(ids)
  if not project:return None
  norm=self.reader.read('model.norm.weight');h=self.norm(hidden[-1:],norm);del norm
  rows=max(1,min(1024,(4*1048576)//(self.hidden*4)));out=[]
  for start in range(0,self.config['vocab_size'],rows):
   self.checkpoint();self.check(rows*self.hidden*8+8*1048576)
   w=self.reader.read(self.head,start,min(start+rows,self.config['vocab_size']));out.append(h@w.T);del w
  return np.concatenate(out,axis=-1)[0]
 def reset(self):self.cache=[None]*self.layers;self.position=0;gc.collect()
 def generate(self,messages,max_tokens=128,temperature=0.7):
  if not 1<=int(max_tokens)<=4096 or not math.isfinite(float(temperature)) or not 0<=temperature<=2:raise ValueError('Invalid generation options')
  self.cancel.clear();self.reset();started=time.perf_counter();read_before=self.reader.bytes_read
  self.stats.update(generated_tokens=0,input_tokens=0,generation_seconds=0.0,tokens_per_second=0.0,time_to_first_token_seconds=None,generation_bytes_read=0)
  try:
   ids=self.tokenizer.encode(self.tokenizer.chat(messages));self.stats['input_tokens']=len(ids)
   if len(ids)+max_tokens>self.context:raise ValueError('Conversation is too long. Start a new chat or raise context.')
   logits=None
   for i in range(0,len(ids),16):logits=self.forward(ids[i:i+16],project=i+16>=len(ids))
   eos=self.config.get('eos_token_id');eos=set(eos if isinstance(eos,list) else [eos]);generated=[];sent=''
   for i in range(max_tokens):
    self.checkpoint()
    if temperature<=0:token=int(logits.argmax())
    else:
     top=np.argpartition(logits,-min(40,len(logits)))[-40:];prob=np.exp((logits[top]-logits[top].max())/max(.05,temperature));prob/=prob.sum();token=int(np.random.choice(top,p=prob))
    if token in eos:break
    generated.append(token);self.stats['generated_tokens']=len(generated)
    if self.stats['time_to_first_token_seconds'] is None:self.stats['time_to_first_token_seconds']=time.perf_counter()-started
    text=self.tokenizer.decode(generated).rstrip('\ufffd')
    if not text.startswith(sent):raise ValueError('Unsupported tokenizer decoding')
    delta=text[len(sent):];sent=text
    if delta:yield delta
    if i+1<max_tokens:logits=self.forward([token])
  finally:
   self.reset();self.stats['current_group']='idle';elapsed=time.perf_counter()-started
   self.stats.update(generation_seconds=elapsed,tokens_per_second=self.stats['generated_tokens']/max(elapsed,1e-9),generation_bytes_read=self.reader.bytes_read-read_before)
