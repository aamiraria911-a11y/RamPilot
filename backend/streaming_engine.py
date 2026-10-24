"""Explicit disk -> CPU -> release inference for dense Qwen2 and Llama models.

No model-wide state_dict, weight mmap, CUDA, prefetch, or complete embedding/head
allocation is used. Only JSON metadata, activations and the KV cache persist.
"""
from __future__ import annotations
import time
import math
import contextlib, gc, json, math, os, struct, threading, time, weakref
from pathlib import Path
import psutil
import torch
from transformers import AutoConfig, AutoTokenizer
from transformers.cache_utils import DynamicCache
from transformers.models.qwen2.modeling_qwen2 import Qwen2DecoderLayer, Qwen2RotaryEmbedding
from transformers.models.llama.modeling_llama import LlamaDecoderLayer, LlamaRotaryEmbedding

DTYPES = {"F32": (torch.float32, 4), "F16": (torch.float16, 2), "BF16": (torch.bfloat16, 2)}
class Cancelled(Exception): pass

class TensorReader:
    """Read only requested byte ranges from validated SafeTensors headers."""
    def __init__(self, folder: Path):
        self.folder = folder.resolve()
        self.entries = {}
        self.bytes_read = 0
        index = self.folder / "model.safetensors.index.json"
        if index.exists():
            names = sorted(set(json.loads(index.read_text("utf-8"))["weight_map"].values()))
        else:
            names = [p.name for p in sorted(self.folder.glob("model*.safetensors"))]
        if not names: raise ValueError("No model SafeTensors files were found. GGUF files cannot be used by this streaming backend.")
        for name in names:
            if Path(name).name != name: raise ValueError("Invalid shard path in model index.")
            path = self.folder / name
            size = path.stat().st_size
            with path.open("rb", buffering=0) as f:
                raw = f.read(8)
                if len(raw) != 8: raise ValueError("Truncated SafeTensors header.")
                length = struct.unpack("<Q", raw)[0]
                if not 2 <= length <= min(size-8, 32*1024*1024): raise ValueError("Invalid SafeTensors header length.")
                header = json.loads(f.read(length))
            intervals = []
            for key, info in header.items():
                if key == "__metadata__": continue
                if key in self.entries: raise ValueError("Duplicate model tensor: " + key)
                dtype = info.get("dtype")
                if dtype not in DTYPES: raise ValueError("Only F32/F16/BF16 SafeTensors weights are supported, not quantized checkpoints.")
                shape = info["shape"]
                if not shape or len(shape)>4 or any(type(d) is not int or d<=0 for d in shape): raise ValueError("Invalid tensor dimensions.")
                begin,end = info["data_offsets"]
                if type(begin) is not int or type(end) is not int or not 0<=begin<end<=size-8-length: raise ValueError("Invalid tensor byte range.")
                if math.prod(shape)*DTYPES[dtype][1] != end-begin: raise ValueError("Tensor size does not match its dimensions.")
                intervals.append((begin,end))
                self.entries[key] = (path, 8+length+begin, tuple(shape), dtype)
            intervals.sort()
            if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])): raise ValueError("Overlapping SafeTensors ranges.")
        self.disk_bytes = sum(p.stat().st_size for p in {v[0] for v in self.entries.values()})

    def _read(self, key, byte_offset=0, elements=None):
        path,start,shape,dtype = self.entries[key]
        torch_dtype,width = DTYPES[dtype]
        if elements is None: elements=math.prod(shape)
        data=bytearray(elements*width)
        with path.open("rb",buffering=0) as f:
            f.seek(start+byte_offset)
            view=memoryview(data)
            done=0
            while done<len(data):
                n=f.readinto(view[done:])
                if not n: raise IOError("Model file was truncated while reading weights.")
                done+=n
        self.bytes_read+=len(data)
        # frombuffer takes ownership through its reference to data. Conversion
        # releases the source bytearray on return for F16 and BF16 weights.
        return torch.frombuffer(data,dtype=torch_dtype).to(dtype=torch.float32)

    def tensor(self,key): return self._read(key).reshape(self.entries[key][2])
    def rows(self,key,begin,end):
        shape=self.entries[key][2]
        if len(shape)!=2 or not 0<=begin<end<=shape[0]: raise ValueError("Invalid matrix row range.")
        return self._read(key,begin*shape[1]*DTYPES[self.entries[key][3]][1],(end-begin)*shape[1]).reshape(end-begin,shape[1])

class StreamingModel:
    def __init__(self, folder, context=2048, budget_mib=4096, threads=2, trace=None, tokenizer=True):
        self.folder=Path(folder).resolve()
        self.context=max(64,min(int(context),8192))
        self.budget=max(256,int(budget_mib))*1024*1024
        self.process=psutil.Process() if os.name=="nt" else None
        self.cancel=threading.Event()
        self.trace=trace
        self.progress=lambda: None
        self.stats={"backend":"explicit-layer-streaming", "current_group":"idle", "live_weight_groups":0,
                    "peak_live_weight_groups":0,"live_weight_bytes":0,"peak_live_weight_bytes":0,
                    "released_groups":0,"release_checks":0,"layer_count":0,"token_count":0}
        torch.set_num_threads(max(1,min(int(threads),os.cpu_count() or 1)))
        torch.set_grad_enabled(False)
        self.config=AutoConfig.from_pretrained(str(self.folder),local_files_only=True,trust_remote_code=False)
        if self.config.model_type not in ("qwen2","llama"):
            raise ValueError("Layer streaming currently supports dense Qwen2/Qwen2.5 and Llama SafeTensors models.")
        if getattr(self.config,"quantization_config",None): raise ValueError("Use a non-quantized F16/BF16/F32 SafeTensors checkpoint.")
        if getattr(self.config,"use_sliding_window",False): raise ValueError("Sliding-window variants are not supported in this build.")
        self.config._attn_implementation="eager"
        self.context=min(self.context,self.config.max_position_embeddings)
        self.layer_class,self.rope_class=(Qwen2DecoderLayer,Qwen2RotaryEmbedding) if self.config.model_type=="qwen2" else (LlamaDecoderLayer,LlamaRotaryEmbedding)
        self.reader=TensorReader(self.folder)
        self.groups=[]
        for i in range(self.config.num_hidden_layers):
            prefix=f"model.layers.{i}."
            keys=sorted(k for k in self.reader.entries if k.startswith(prefix))
            if not keys: raise ValueError("Missing decoder layer "+str(i))
            self.groups.append((prefix,keys))
        self.stats["layer_count"]=len(self.groups)
        self.embed_key="model.embed_tokens.weight"
        self.head_key="lm_head.weight" if "lm_head.weight" in self.reader.entries else self.embed_key
        for key in [self.embed_key,self.head_key,"model.norm.weight"]:
            if key not in self.reader.entries: raise ValueError("Missing weight: "+key)
        expected=(self.config.vocab_size,self.config.hidden_size)
        if self.reader.entries[self.embed_key][2]!=expected or self.reader.entries[self.head_key][2]!=expected: raise ValueError("Vocabulary shape does not match model config.")
        if self.head_key==self.embed_key and not self.config.tie_word_embeddings: raise ValueError("Untied output head is missing.")
        self.rope=self.rope_class(self.config,device="cpu")
        self.tokenizer=AutoTokenizer.from_pretrained(str(self.folder),local_files_only=True,trust_remote_code=False) if tokenizer else None
        # Check the biggest layer before generation, including conversion scratch,
        # a bounded KV cache and processing workspace. Never load full weights.
        largest=max(sum(math.prod(self.reader.entries[k][2])*4 for k in keys) for _,keys in self.groups)
        largest_source=max(math.prod(v[2])*DTYPES[v[3]][1] for k,v in self.reader.entries.items() if k.startswith("model.layers."))
        head_dim=getattr(self.config,"head_dim",None) or self.config.hidden_size//self.config.num_attention_heads
        self.kv_max=self.context*len(self.groups)*2*self.config.num_key_value_heads*head_dim*4
        self.check_memory(largest+largest_source+self.kv_max+64*1024*1024)
        self.stats["model_disk_bytes"]=self.reader.disk_bytes
        self.stats["largest_layer_fp32_bytes"]=largest
        self.stats["max_kv_cache_bytes"]=self.kv_max
        self.cache=DynamicCache()

    def resident_bytes(self):
        # Read /proc/self instead of a numeric PID on Linux. This also works in
        # PID-translated test hosts. Windows psutil uses the native process API.
        if os.name!="nt":
            try:
                for line in Path("/proc/self/status").read_text().splitlines():
                    if line.startswith("VmRSS:"): return int(line.split()[1])*1024
            except OSError: pass
        if self.process is not None: return self.process.memory_info().rss
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024

    def check_memory(self,extra=0):
        if self.resident_bytes()+extra>self.budget:
            raise MemoryError("The next layer and its working buffers exceed the configured RAM planning budget. Lower context, raise the budget, or select a smaller model.")

    def metrics(self):
        result=dict(self.stats)
        result.update(rss_bytes=self.resident_bytes(),bytes_read=self.reader.bytes_read,budget_bytes=self.budget)
        return result

    def checkpoint(self):
        if self.cancel.is_set(): raise Cancelled("Generation stopped")
        self.progress()

    def record(self,event):
        if self.trace: self.trace(event,dict(self.stats))

    @contextlib.contextmanager
    def weights(self,prefix,keys):
        self.checkpoint()
        if self.stats["live_weight_groups"]: raise RuntimeError("A previous weight group has not been released.")
        needed=sum(math.prod(self.reader.entries[k][2])*4 for k in keys)
        scratch=max(math.prod(self.reader.entries[k][2])*DTYPES[self.reader.entries[k][3]][1] for k in keys)
        self.check_memory(needed+scratch+16*1024*1024)
        self.stats.update(current_group=prefix,live_weight_groups=1,live_weight_bytes=needed)
        self.stats["peak_live_weight_groups"]=max(1,self.stats["peak_live_weight_groups"])
        self.stats["peak_live_weight_bytes"]=max(needed,self.stats["peak_live_weight_bytes"])
        state={}
        refs=[]
        self.record("load")
        try:
            state.update({k[len(prefix):]:self.reader.tensor(k) for k in keys})
            refs=[weakref.ref(t) for t in state.values()]
            self.checkpoint()
            yield state
        finally:
            state.clear()
            gc.collect()
            # Decoder modules are returned to meta before leaving the lease.
            if any(ref() is not None for ref in refs):
                raise RuntimeError("Weight release check failed; refusing to load another group.")
            self.stats.update(current_group="idle",live_weight_groups=0,live_weight_bytes=0)
            self.stats["released_groups"]+=1
            self.stats["release_checks"]+=1
            self.record("release")

    def embeddings(self,ids):
        # Gather only needed token rows. Never allocate the vocabulary matrix.
        flat=ids.reshape(-1).tolist()
        self.check_memory(len(flat)*self.config.hidden_size*4+8*1024*1024)
        result=torch.empty((len(flat),self.config.hidden_size),dtype=torch.float32)
        for i,token in enumerate(flat):
            if not 0<=token<self.config.vocab_size: raise ValueError("Token ID outside model vocabulary.")
            result[i].copy_(self.reader.rows(self.embed_key,token,token+1)[0])
        return result.reshape(1,ids.shape[-1],self.config.hidden_size)

    @torch.inference_mode()
    def forward(self,ids,all_logits=False,project=True):
        self.checkpoint()
        count=self.cache.get_seq_length()
        if ids.ndim!=2 or ids.shape[0]!=1 or ids.shape[1]>32: raise ValueError("Input chunks must contain 1–32 tokens in a single sequence.")
        if count+ids.shape[1]>self.context: raise ValueError("Context limit reached.")
        hidden=self.embeddings(ids)
        positions=torch.arange(count,count+ids.shape[1],dtype=torch.long)
        position_ids=positions.unsqueeze(0)
        total=count+ids.shape[1]
        mask=torch.zeros((ids.shape[1],total),dtype=torch.float32)
        mask.masked_fill_(torch.arange(total).unsqueeze(0)>positions.unsqueeze(1),torch.finfo(torch.float32).min)
        mask=mask.unsqueeze(0).unsqueeze(0)
        rotary=self.rope(hidden,position_ids)
        for i,(prefix,keys) in enumerate(self.groups):
            with self.weights(prefix,keys) as state:
                with torch.device("meta"): layer=self.layer_class(self.config,i)
                try:
                    layer.load_state_dict(state,strict=True,assign=True)
                    layer.eval()
                    hidden=layer(hidden,attention_mask=mask,position_ids=position_ids,past_key_value=self.cache,
                                 use_cache=True,cache_position=positions,position_embeddings=rotary)[0]
                finally:
                    # Explicitly drop parameter storage, including Parameter wrappers.
                    layer.to_empty(device="meta")
                    del layer
        if not project:
            self.stats["token_count"]=total
            return None
        with self.weights("model.norm.",["model.norm.weight"]) as state:
            hidden=hidden*torch.rsqrt(hidden.pow(2).mean(-1,keepdim=True)+self.config.rms_norm_eps)
            hidden=hidden*state["weight"]
        h=hidden[0] if all_logits else hidden[0,-1:]
        outputs=[]
        # Output projection is streamed in bounded row chunks too.
        rows=max(1,min(2048,(8*1024*1024)//(self.config.hidden_size*4)))
        for start in range(0,self.config.vocab_size,rows):
            self.checkpoint()
            self.check_memory(rows*self.config.hidden_size*6+8*1024*1024)
            weight=self.reader.rows(self.head_key,start,min(start+rows,self.config.vocab_size))
            outputs.append(h@weight.T)
            del weight
        self.stats["token_count"]=total
        return torch.cat(outputs,dim=-1)

    def prompt_ids(self,messages):
        if self.tokenizer is None: raise ValueError("Tokenizer is not loaded")
        return self.tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True)

    def reset(self):
        self.cache=DynamicCache()
        self.stats["token_count"]=0
        gc.collect()

    @torch.inference_mode()
    def generate(self,messages,max_tokens=256,temperature=0.7):
        if not 1<=int(max_tokens)<=4096 or not math.isfinite(float(temperature)) or not 0<=temperature<=2: raise ValueError("Invalid generation options")
        self.cancel.clear()
        self.reset()
        started=time.perf_counter();read_before=self.reader.bytes_read
        self.stats.update(generated_tokens=0,input_tokens=0,generation_seconds=0.0,tokens_per_second=0.0,time_to_first_token_seconds=None,generation_bytes_read=0)
        try:
            ids=self.prompt_ids(messages)
            self.stats["input_tokens"]=len(ids)
            if not ids: raise ValueError("Empty prompt")
            if len(ids)+max_tokens>self.context: raise ValueError("Prompt plus requested reply exceeds context. Shorten the conversation or increase Context.")
            logits=None
            for start in range(0,len(ids),32): logits=self.forward(torch.tensor([ids[start:start+32]],dtype=torch.long),project=(start+32>=len(ids)))
            eos=self.config.eos_token_id or self.tokenizer.eos_token_id
            stop=set(eos if isinstance(eos,list) else [eos])
            generated=[]
            emitted=""
            for i in range(max_tokens):
                self.checkpoint()
                scores=logits[0]
                if temperature<=0: token=int(scores.argmax())
                else:
                    values,indices=torch.topk(scores,min(40,len(scores)))
                    token=int(indices[torch.multinomial(torch.softmax(values/max(temperature,0.05),dim=-1),1)])
                if token in stop: break
                generated.append(token)
                self.stats["generated_tokens"]=len(generated)
                if self.stats["time_to_first_token_seconds"] is None:self.stats["time_to_first_token_seconds"]=time.perf_counter()-started
                text=self.tokenizer.decode(generated,skip_special_tokens=True,clean_up_tokenization_spaces=False).rstrip("\ufffd")
                if not text.startswith(emitted): raise ValueError("Tokenizer changed already emitted text; use a supported tokenizer.")
                delta=text[len(emitted):]
                emitted=text
                if delta: yield delta
                if i+1<max_tokens: logits=self.forward(torch.tensor([[token]],dtype=torch.long))
        finally:
            self.reset()
            self.stats["current_group"]="idle"
            elapsed=time.perf_counter()-started
            self.stats.update(generation_seconds=elapsed,tokens_per_second=self.stats["generated_tokens"]/max(elapsed,1e-9),generation_bytes_read=self.reader.bytes_read-read_before)
            self.progress=lambda:None
