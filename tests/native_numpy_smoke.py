"""Exercise the packaged NumPy engine and binary dependencies without downloads."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import numpy as np

# Optional first argument points to the packaged app's Python sources.
sys.path.insert(0,sys.argv[1] if len(sys.argv)>1 else str(Path(__file__).resolve().parents[1]/'mobile'))
from numpy_streamer import NumpyStreamingModel

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    config=dict(model_type='qwen2',hidden_size=16,intermediate_size=32,num_hidden_layers=2,
                num_attention_heads=2,num_key_value_heads=1,max_position_embeddings=128,
                vocab_size=64,rms_norm_eps=1e-6,rope_theta=10000,tie_word_embeddings=True)
    (root/'config.json').write_text(json.dumps(config))
    rng=np.random.default_rng(123)
    values={'model.embed_tokens.weight':rng.normal(0,.02,(64,16)).astype('<f4'),
            'model.norm.weight':np.ones(16,dtype='<f4')}
    for index in range(2):
        prefix=f'model.layers.{index}.'
        shapes={'input_layernorm.weight':(16,), 'post_attention_layernorm.weight':(16,),
                'self_attn.q_proj.weight':(16,16),'self_attn.k_proj.weight':(8,16),'self_attn.v_proj.weight':(8,16),
                'self_attn.o_proj.weight':(16,16),'self_attn.q_proj.bias':(16,),'self_attn.k_proj.bias':(8,),
                'self_attn.v_proj.bias':(8,),'mlp.gate_proj.weight':(32,16),'mlp.up_proj.weight':(32,16),'mlp.down_proj.weight':(16,32)}
        for name,shape in shapes.items():
            values[prefix+name]=np.ones(shape,dtype='<f4') if 'layernorm' in name else rng.normal(0,.02,shape).astype('<f4')
    header={};offset=0;payload=[]
    for name,value in values.items():
        block=value.tobytes();header[name]=dict(dtype='F32',shape=list(value.shape),data_offsets=[offset,offset+len(block)])
        offset+=len(block);payload.append(block)
    raw=json.dumps(header).encode();raw+=b' '*((-len(raw))%8)
    (root/'model.safetensors').write_bytes(struct.pack('<Q',len(raw))+raw+b''.join(payload))
    model=NumpyStreamingModel(root,128,2048,tokenizer=False)
    output=model.forward([1,4,6]);second=model.forward([7])
    assert output.shape==(64,) and np.isfinite(output).all() and np.isfinite(second).all()
    assert model.stats['peak_live_weight_groups']==1 and model.stats['live_weight_groups']==0
    model.reset()
    assert model.position==0
    print('PASS: native NumPy matmul, CPU inference, cached decoding and layer release')
