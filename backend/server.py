"""Authenticated loopback protocol used by the RamPilot Windows UI."""
import argparse, hmac, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",TOKENIZERS_PARALLELISM="false")
from streaming_engine import StreamingModel, Cancelled


def resolve_manifest(path):
    manifest=Path(path).resolve()
    if manifest.suffix!=".json": raise ValueError("Choose a layer-streaming model, not a GGUF file.")
    data=json.loads(manifest.read_text("utf-8"))
    if data.get("format")!="rampilot-safetensors-v1": raise ValueError("Invalid RamPilot streaming manifest.")
    folder=Path(data["model_dir"])
    return folder.resolve() if folder.is_absolute() else (manifest.parent/folder).resolve()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--manifest",required=True);parser.add_argument("--port",type=int,required=True)
    parser.add_argument("--context",type=int,default=2048);parser.add_argument("--budget-mib",type=int,default=4096)
    parser.add_argument("--threads",type=int,default=2)
    args=parser.parse_args()
    key=os.environ.pop("RAMPILOT_SESSION_KEY",None)
    if not key: raise RuntimeError("A session key is required")
    model=StreamingModel(resolve_manifest(args.manifest),args.context,args.budget_mib,args.threads)
    lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        protocol_version="HTTP/1.1"
        def log_message(self,*args):pass
        def auth(self):
            if not hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+key):
                self.reply(401,{"error":"Authentication required"});return False
            return True
        def reply(self,status,data):
            payload=json.dumps(data).encode();self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload)
        def do_GET(self):
            if not self.auth():return
            if self.path=="/health":self.reply(200,{"status":"ok","backend":"explicit-layer-streaming"})
            elif self.path=="/metrics":self.reply(200,model.metrics())
            else:self.reply(404,{"error":"Not found"})
        def do_POST(self):
            if not self.auth():return
            try:
                size=int(self.headers.get("Content-Length","0"))
                if not 0<=size<=4*1024*1024:raise ValueError("Request is too large")
                data=json.loads(self.rfile.read(size))
                if self.path=="/cancel":model.cancel.set();self.reply(200,{"cancelled":True});return
                if self.path=="/apply-template":
                    prompt=model.tokenizer.apply_chat_template(data["messages"],tokenize=False,add_generation_prompt=True)
                    self.reply(200,{"prompt":prompt});return
                if self.path=="/tokenize":self.reply(200,{"tokens":model.tokenizer.encode(data["content"],add_special_tokens=bool(data.get("add_special",False)))});return
                if self.path!="/v1/chat/completions":self.reply(404,{"error":"Not found"});return
                if not data.get("stream"):raise ValueError("Use streaming chat completions")
                if not lock.acquire(blocking=False):self.reply(409,{"error":"A generation is already running"});return
                try:
                    model.stats["generating"]=True
                    max_tokens=int(data.get("max_tokens",256));temperature=float(data.get("temperature",0.7))
                    if not 1<=max_tokens<=4096 or not 0<=temperature<=2:raise ValueError("Invalid generation options")
                    self.send_response(200);self.send_header("Content-Type","text/event-stream; charset=utf-8");self.send_header("Cache-Control","no-cache");self.send_header("Connection","close");self.end_headers();self.close_connection=True
                    last=[0.0]
                    def heartbeat():
                        if time.monotonic()-last[0]>0.5:
                            self.wfile.write(b": working\n\n");self.wfile.flush();last[0]=time.monotonic()
                    def send(value):self.wfile.write(("data: "+value+"\n\n").encode("utf-8"));self.wfile.flush()
                    model.progress=heartbeat
                    try:
                        for text in model.generate(data["messages"],max_tokens,temperature):send(json.dumps({"choices":[{"delta":{"content":text}}]}))
                        send("[DONE]")
                    except Cancelled:send(json.dumps({"error":"Generation stopped"}))
                    except (BrokenPipeError,ConnectionResetError):model.cancel.set()
                    except Exception as exc:
                        print(type(exc).__name__+": "+str(exc),file=sys.stderr,flush=True)
                        send(json.dumps({"error":str(exc)}))
                    finally:model.progress=lambda:None
                finally:model.stats["generating"]=False;lock.release()
            except (BrokenPipeError,ConnectionResetError):model.cancel.set()
            except Exception as exc:self.reply(400,{"error":str(exc)})
    print("RamPilot explicit layer streaming ready. "+str(model.metrics()),flush=True)
    server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    server.daemon_threads=True
    server.serve_forever()
if __name__=="__main__":main()
