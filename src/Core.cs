using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using System.Collections;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Security.Cryptography;
using System.Runtime.InteropServices;

namespace RamPilot {
 public static class Json {
  public static string Encode(object value) { return new JavaScriptSerializer { MaxJsonLength=16777216 }.Serialize(value); }
  public static T Decode<T>(string value) { return new JavaScriptSerializer { MaxJsonLength=16777216 }.Deserialize<T>(value); }
  public static Dictionary<string,object> Object(string value) { return Decode<Dictionary<string,object>>(value); }
 }
 public class Message { public string role {get;set;} public string content {get;set;} public Message(){} public Message(string r,string c){role=r;content=c;} }
 public class ModelInfo {
  public string Name {get;set;} public string FileName {get;set;} public string Url {get;set;} public string Sha256 {get;set;}
  public string DirectoryName {get;set;} public string Repo{get;set;} public string Revision{get;set;} public List<ModelFile> Files{get;set;}
  public long Bytes {get;set;} public string Description {get;set;} public string License {get;set;} public string Page {get;set;}
  public override string ToString(){return Name;}
 }
 public class Settings {
  public string ModelPath {get;set;} = "";
  public string Mode {get;set;} = "Layer streaming";
  public int Context {get;set;} = 2048;
  public int Threads {get;set;} = Math.Max(1, Environment.ProcessorCount/2);
  public int BudgetGiB {get;set;} = 4;
  public int MaxTokens {get;set;} = 256;
  public double Temperature {get;set;} = 0.7;
  public string ConversationId {get;set;} = "";
  public string SystemPrompt {get;set;} = "You are a helpful assistant. Give clear, accurate answers.";
  public bool SaveChat {get;set;} = true;
 }
 public static class Store {
  public static string Root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"RamPilot");
  public static string Models {get{return Path.Combine(Root,"Models");}}
  public static void Initialize(){Directory.CreateDirectory(Root);Directory.CreateDirectory(Models);}
  public static void Write(string name,object value) {
   string path=Path.Combine(Root,name), tmp=path+".tmp";
   File.WriteAllText(tmp,Json.Encode(value),new UTF8Encoding(false));
   if(File.Exists(path)) File.Replace(tmp,path,null); else File.Move(tmp,path);
  }
  public static T Read<T>(string name,T fallback) {
   try {var v=Json.Decode<T>(File.ReadAllText(Path.Combine(Root,name)));return v==null?fallback:v;}catch{return fallback;}
  }
 }
 public class MemoryInfo {
  public ulong Total, Available;
  [StructLayout(LayoutKind.Sequential)] class MEMORYSTATUSEX {
   public uint Length=(uint)Marshal.SizeOf(typeof(MEMORYSTATUSEX)), Load;
   public ulong TotalPhys,AvailPhys,TotalPageFile,AvailPageFile,TotalVirtual,AvailVirtual,AvailExtendedVirtual;
  }
  [DllImport("kernel32.dll",SetLastError=true)] static extern bool GlobalMemoryStatusEx([In,Out] MEMORYSTATUSEX m);
  public static MemoryInfo Read() {
   try {var m=new MEMORYSTATUSEX();if(GlobalMemoryStatusEx(m))return new MemoryInfo{Total=m.TotalPhys,Available=m.AvailPhys};}catch{}
   try {
    var lines=File.ReadAllLines("/proc/meminfo");
    Func<string,ulong> get=k=>UInt64.Parse(lines.First(x=>x.StartsWith(k)).Split(new[]{' '},StringSplitOptions.RemoveEmptyEntries)[1])*1024;
    return new MemoryInfo{Total=get("MemTotal:"),Available=get("MemAvailable:")};
   }catch{return new MemoryInfo();}
  }
  public static string GiB(double bytes){return (bytes/1073741824.0).ToString("0.0")+" GB";}
 }
 public class RunProfile {
  public int Context, Batch, UBatch;
  public bool Lazy;
  public static RunProfile From(Settings s) {
   bool disk=s.Mode=="SSD paging";
   bool low=s.Mode!="Balanced";
   return new RunProfile {Context=Math.Max(512,Math.Min(32768,s.Context)), Batch=low?64:256,UBatch=low?32:128,Lazy=disk};
  }
  public static string Quote(string arg) {
   // Windows CommandLineToArgvW quoting, including trailing slashes and embedded quotes.
   var b=new StringBuilder("\"");int slashes=0;
   foreach(char c in arg){if(c=='\\'){slashes++;continue;}if(c=='"'){b.Append('\\',slashes*2+1);b.Append('"');slashes=0;continue;}b.Append('\\',slashes);slashes=0;b.Append(c);}
   b.Append('\\',slashes*2);return b.Append('"').ToString();
  }
  public string Arguments(string model,Settings s,int port,string key) {
   return "--model "+Quote(model)+" --host 127.0.0.1 --port "+port+
    " --api-key "+key+" --device none --n-gpu-layers 0 --load-mode mmap --lazy-mode "+(Lazy?"on":"auto")+
    " --no-warmup --fit off --ctx-size "+Context+" --batch-size "+Batch+" --ubatch-size "+UBatch+
    " --threads "+Math.Max(1,Math.Min(Environment.ProcessorCount,s.Threads))+" --parallel 1 --no-webui";
  }
 }
 public static class Gguf {
  public static void Validate(string path) {
   if(!File.Exists(path))throw new IOException("The model file no longer exists. Choose it again.");
   using(var f=File.OpenRead(path)){var magic=new byte[4];if(f.Read(magic,0,4)!=4 || Encoding.ASCII.GetString(magic)!="GGUF")throw new IOException("This is not a GGUF model. Import a complete .gguf file.");}
   if(Path.GetFileName(path).Contains("-of-"))throw new IOException("Split GGUF imports are not supported in this version. Choose a single-file GGUF model.");
  }
 }
 public class DownloadProgress { public long Done,Total;public string Stage; }
 public static class Downloader {
  public static async Task FetchAsync(ModelInfo model,string destination,IProgress<DownloadProgress> progress,CancellationToken ct,HttpMessageHandler handler=null,bool validateGguf=false) {
   if(!Uri.IsWellFormedUriString(model.Url,UriKind.Absolute)||new Uri(model.Url).Scheme!="https")throw new IOException("Downloads require HTTPS.");
   if(Path.GetFileName(model.FileName)!=model.FileName)throw new IOException("Invalid model filename.");
   Directory.CreateDirectory(Path.GetDirectoryName(destination));
   string part=destination+".part";
   long offset=File.Exists(part)?new FileInfo(part).Length:0;
   if(offset>model.Bytes){File.Delete(part);offset=0;}
   // The catalog is pinned to a repository commit and SHA-256. Partial data is never loaded.
   if(offset<model.Bytes) {
    using(var client=new HttpClient(handler ?? new HttpClientHandler())) {
     client.Timeout=Timeout.InfiniteTimeSpan;client.DefaultRequestHeaders.UserAgent.ParseAdd("RamPilot/2.1");
     using(var request=new HttpRequestMessage(HttpMethod.Get,model.Url)) {
      if(offset>0)request.Headers.Range=new RangeHeaderValue(offset,null);
      using(var response=await client.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,ct).ConfigureAwait(false)) {
       response.EnsureSuccessStatusCode();
       if(response.RequestMessage!=null&&response.RequestMessage.RequestUri.Scheme!="https")throw new IOException("The download redirected to an insecure connection.");
       if(response.StatusCode!=HttpStatusCode.OK&&response.StatusCode!=HttpStatusCode.PartialContent)throw new IOException("Unexpected download response.");
       if(response.StatusCode==HttpStatusCode.PartialContent) {
        var range=response.Content.Headers.ContentRange;
        if(range==null||range.From!=offset||range.To!=model.Bytes-1||range.Length!=model.Bytes)throw new IOException("The download server returned an invalid resume range. Delete the .part file and retry.");
       } else offset=0;
       long remaining=model.Bytes-offset;
       if(response.Content.Headers.ContentLength.HasValue && response.Content.Headers.ContentLength.Value!=remaining)throw new IOException("Download size does not match the verified catalog.");
       using(var source=await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
       using(var target=new FileStream(part,offset>0?FileMode.Append:FileMode.Create,FileAccess.Write,FileShare.None,131072,true))
       using(ct.Register(()=>source.Dispose())) {
        var buffer=new byte[131072];long done=offset;var clock=Stopwatch.StartNew();
        while(true) {
         ct.ThrowIfCancellationRequested();int n=await source.ReadAsync(buffer,0,buffer.Length,ct).ConfigureAwait(false);if(n==0)break;
         done+=n;if(done>model.Bytes)throw new IOException("Download exceeded the expected model size.");
         await target.WriteAsync(buffer,0,n,ct).ConfigureAwait(false);
         if(clock.ElapsedMilliseconds>150){progress.Report(new DownloadProgress{Done=done,Total=model.Bytes,Stage="Downloading"});clock.Restart();}
        }
        if(done!=model.Bytes)throw new IOException("Download interrupted. Click Download to resume.");
       }
      }
     }
    }
   }
   progress.Report(new DownloadProgress{Done=model.Bytes,Total=model.Bytes,Stage="Verifying SHA-256"});
   bool valid=await Task.Run(()=>{
    using(var sha=SHA256.Create())using(var input=File.OpenRead(part)){
     var buffer=new byte[1024*1024];int n;while((n=input.Read(buffer,0,buffer.Length))>0){ct.ThrowIfCancellationRequested();sha.TransformBlock(buffer,0,n,null,0);}sha.TransformFinalBlock(new byte[0],0,0);
     return BitConverter.ToString(sha.Hash).Replace("-","").Equals(model.Sha256,StringComparison.OrdinalIgnoreCase);
    }
   },ct).ConfigureAwait(false);
   if(!valid){File.Delete(part);throw new IOException("Model checksum failed. The incomplete file was removed. Try downloading again.");}
   if(validateGguf)Gguf.Validate(part);ct.ThrowIfCancellationRequested();
   if(File.Exists(destination))throw new IOException("A model already exists at that path. Your existing file was kept.");
   File.Move(part,destination);
  }
 }
 // A job object closes the inference process if the app exits unexpectedly.
 public sealed class ProcessJob:IDisposable {
  IntPtr handle;
  [StructLayout(LayoutKind.Sequential)] struct Basic {public long PerProcessUserTimeLimit,PerJobUserTimeLimit;public uint LimitFlags;public UIntPtr MinimumWorkingSetSize,MaximumWorkingSetSize;public uint ActiveProcessLimit;public UIntPtr Affinity;public uint PriorityClass,SchedulingClass;}
  [StructLayout(LayoutKind.Sequential)] struct IO {public ulong ReadOperationCount,WriteOperationCount,OtherOperationCount,ReadTransferCount,WriteTransferCount,OtherTransferCount;}
  [StructLayout(LayoutKind.Sequential)] struct Extended {public Basic BasicLimitInformation;public IO IoInfo;public UIntPtr ProcessMemoryLimit,JobMemoryLimit,PeakProcessMemoryUsed,PeakJobMemoryUsed;}
  [DllImport("kernel32.dll",CharSet=CharSet.Unicode)]static extern IntPtr CreateJobObject(IntPtr attr,string name);
  [DllImport("kernel32.dll")]static extern bool SetInformationJobObject(IntPtr job,int cls,ref Extended info,uint size);
  [DllImport("kernel32.dll")]static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
  [DllImport("kernel32.dll")]static extern bool CloseHandle(IntPtr h);
  public ProcessJob(Process p) {
   if(Environment.OSVersion.Platform!=PlatformID.Win32NT)return;
   handle=CreateJobObject(IntPtr.Zero,null);var info=new Extended();info.BasicLimitInformation.LimitFlags=0x2000;
   if(handle==IntPtr.Zero||!SetInformationJobObject(handle,9,ref info,(uint)Marshal.SizeOf(info))||!AssignProcessToJobObject(handle,p.Handle)){
    Dispose();throw new IOException("Windows could not attach the engine to the app's process group. Close other sandboxing software and retry.");
   }
  }
  public void Dispose(){if(handle!=IntPtr.Zero){CloseHandle(handle);handle=IntPtr.Zero;}}
 }
 public sealed class Engine:IDisposable {
  readonly Func<HttpMessageHandler> handlerFactory;
  public Engine(Func<HttpMessageHandler> handlerFactory=null){this.handlerFactory=handlerFactory ?? (()=>new HttpClientHandler{UseProxy=false});}
  Process process;ProcessJob job;HttpClient client;readonly Queue<string> logs=new Queue<string>();
  public bool Ready {get;private set;}
  public string LoadedModel {get;private set;}
  public int Context {get;private set;}
  public int Port {get;private set;}
  public string Executable=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"engine","python","python.exe");
  public string BackendScript=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"engine","backend","server.py");
  public Dictionary<string,object> Metrics {get;private set;}
  public bool Running {get{try{return process!=null&&!process.HasExited;}catch{return false;}}}
  public long WorkingSet {get{try{process.Refresh();return process.WorkingSet64;}catch{return 0;}}}
  public string LogTail {get{lock(logs)return string.Join(Environment.NewLine,logs.ToArray());}}
  void Log(string text){if(text==null)return;lock(logs){logs.Enqueue(text);while(logs.Count>160)logs.Dequeue();}}
  public async Task StartAsync(string model,Settings settings,IProgress<string> progress,CancellationToken ct) {
   Stop();if(!model.EndsWith(".stream.json",StringComparison.OrdinalIgnoreCase)||!File.Exists(model))throw new IOException("Choose a SafeTensors layer-streaming model from Models. GGUF files use the old backend.");if(!File.Exists(Executable)||!File.Exists(BackendScript))throw new IOException("The bundled CPU engine is missing. Reinstall RamPilot.");
   var listener=new TcpListener(IPAddress.Loopback,0);listener.Start();Port=((IPEndPoint)listener.LocalEndpoint).Port;listener.Stop();
   string key=Guid.NewGuid().ToString("N")+Guid.NewGuid().ToString("N");var profile=RunProfile.From(settings);Context=Math.Min(8192,profile.Context);
   client=new HttpClient(handlerFactory());client.Timeout=Timeout.InfiniteTimeSpan;
   client.BaseAddress=new Uri("http://127.0.0.1:"+Port+"/");client.DefaultRequestHeaders.Authorization=new AuthenticationHeaderValue("Bearer",key);
   lock(logs)logs.Clear();
   var args=RunProfile.Quote(BackendScript)+" --manifest "+RunProfile.Quote(model)+" --port "+Port+" --context "+Context+" --budget-mib "+(settings.BudgetGiB*1024)+" --threads "+Math.Max(1,Math.Min(Environment.ProcessorCount,settings.Threads));
   var start=new ProcessStartInfo(Executable,args) {UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true,RedirectStandardOutput=true,WorkingDirectory=Path.GetDirectoryName(Executable)};
   // Avoid inherited llama.cpp flags changing CPU, network or tool behavior.
   foreach(string name in start.EnvironmentVariables.Keys.Cast<string>().ToArray())if(name.StartsWith("LLAMA_",StringComparison.OrdinalIgnoreCase))start.EnvironmentVariables.Remove(name);
   start.EnvironmentVariables["RAMPILOT_SESSION_KEY"]=key;
   start.EnvironmentVariables["HF_HUB_OFFLINE"]="1";start.EnvironmentVariables["TRANSFORMERS_OFFLINE"]="1";start.EnvironmentVariables["CUDA_VISIBLE_DEVICES"]="";
   process=new Process{StartInfo=start};process.ErrorDataReceived+=(s,e)=>Log(e.Data);process.OutputDataReceived+=(s,e)=>Log(e.Data);
   try {
    if(!process.Start())throw new IOException("Could not start the CPU engine.");job=new ProcessJob(process);process.BeginErrorReadLine();process.BeginOutputReadLine();
    progress.Report("Reading model metadata and tokenizer. Decoder weights remain on disk until generation...");var time=Stopwatch.StartNew();
    while(true) {
     ct.ThrowIfCancellationRequested();if(process.HasExited)throw new IOException("The engine exited during model loading. Open Engine log for details.\n\n"+LogTail);
     if(time.Elapsed>TotalLoadTimeout)throw new IOException("Model loading exceeded 20 minutes. Try a smaller model or a shorter context.");
     using(var poll=CancellationTokenSource.CreateLinkedTokenSource(ct)) {
      poll.CancelAfter(2000);
      try {using(var response=await client.GetAsync("health",poll.Token).ConfigureAwait(false))if(response.IsSuccessStatusCode){Ready=true;LoadedModel=model;return;}}catch(HttpRequestException ex){Log("Waiting for local server: "+ex.Message);}catch(OperationCanceledException){ct.ThrowIfCancellationRequested();}
     }
     await Task.Delay(400,ct).ConfigureAwait(false);
    }
   }catch {Stop();throw;}
  }
  static readonly TimeSpan TotalLoadTimeout=TimeSpan.FromMinutes(20);
  async Task<Dictionary<string,object>> PostAsync(string endpoint,object payload,CancellationToken ct) {
   using(var body=new StringContent(Json.Encode(payload),Encoding.UTF8,"application/json"))
   using(var r=await client.PostAsync(endpoint,body,ct).ConfigureAwait(false)){
    string text=await r.Content.ReadAsStringAsync().ConfigureAwait(false);if(!r.IsSuccessStatusCode)throw new IOException("The model could not process this conversation: "+text);
    return Json.Object(text);
   }
  }
  public async Task<int> CountTokensAsync(List<Message> messages,CancellationToken ct) {
   var rendered=await PostAsync("apply-template",new{messages=messages,add_generation_prompt=true},ct).ConfigureAwait(false);
   var result=await PostAsync("tokenize",new{content=Convert.ToString(rendered["prompt"]),add_special=true},ct).ConfigureAwait(false);
   return ((IList)result["tokens"]).Count;
  }
  public async Task<List<Message>> FitAsync(List<Message> history,int maxTokens,IProgress<string> progress,CancellationToken ct) {
   var copy=history.Select(m=>new Message(m.role,m.content)).ToList();int removed=0;
   while(await CountTokensAsync(copy,ct).ConfigureAwait(false)+maxTokens+32>Context) {
    // Preserve system + current user. Remove complete old user/assistant pairs.
    if(copy.Count<=2)throw new IOException("This message is too long for the selected context. Shorten it or increase Context in Settings, then reload the model.");
    copy.RemoveAt(1);removed++;if(copy.Count>2&&copy[1].role=="assistant"){copy.RemoveAt(1);removed++;}
   }
   if(removed>0)progress.Report("Earlier turns were omitted from this request to fit the context.");
   return copy;
  }
  public async Task GenerateAsync(List<Message> messages,int maxTokens,IProgress<string> output,CancellationToken ct) {
   await GenerateAsync(messages,maxTokens,0.7,output,ct).ConfigureAwait(false);
  }
  public async Task GenerateAsync(List<Message> messages,int maxTokens,double temperature,IProgress<string> output,CancellationToken ct) {
   try {await GenerateInternalAsync(messages,maxTokens,temperature,output,ct).ConfigureAwait(false);}
   finally {if(ct.IsCancellationRequested&&Running)await CancelAndWaitAsync().ConfigureAwait(false);}
  }
  public async Task RefreshMetricsAsync() {
   if(!Ready||client==null)return;
   using(var timeout=new CancellationTokenSource(1500)){try{using(var r=await client.GetAsync("metrics",timeout.Token).ConfigureAwait(false)){if(r.IsSuccessStatusCode)Metrics=Json.Object(await r.Content.ReadAsStringAsync().ConfigureAwait(false));}}catch{}}
  }
  async Task CancelAndWaitAsync() {
   try{using(var timeout=new CancellationTokenSource(5000)){await PostAsync("cancel",new{},timeout.Token).ConfigureAwait(false);for(int i=0;i<25;i++){await RefreshMetricsAsync().ConfigureAwait(false);if(Metrics!=null&&Metrics.ContainsKey("generating")&&!Convert.ToBoolean(Metrics["generating"]))return;await Task.Delay(100,timeout.Token).ConfigureAwait(false);}}}catch{}
   Stop();
  }
  async Task GenerateInternalAsync(List<Message> messages,int maxTokens,double temperature,IProgress<string> output,CancellationToken ct) {
   if(!Ready||!Running)throw new IOException("Load a model first.");
   var payload=new{messages=messages,stream=true,max_tokens=maxTokens,temperature=temperature,cache_prompt=true};
   using(var request=new HttpRequestMessage(HttpMethod.Post,"v1/chat/completions")) {
    request.Content=new StringContent(Json.Encode(payload),Encoding.UTF8,"application/json");
    using(var response=await client.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,ct).ConfigureAwait(false)) {
     if(!response.IsSuccessStatusCode)throw new IOException(await response.Content.ReadAsStringAsync().ConfigureAwait(false));
     using(var stream=await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
     using(var reader=new StreamReader(stream,Encoding.UTF8))
     using(ct.Register(()=>response.Dispose())) {
      while(true) {
       ct.ThrowIfCancellationRequested();string line;
       try{line=await reader.ReadLineAsync().ConfigureAwait(false);}catch{ct.ThrowIfCancellationRequested();throw;}
       if(line==null)throw new IOException("The engine disconnected before finishing its answer.");
       if(!line.StartsWith("data: "))continue;string data=line.Substring(6);if(data=="[DONE]")break;
       var chunk=Json.Object(data);if(chunk.ContainsKey("error"))throw new IOException(Json.Encode(chunk["error"]));
       if(!chunk.ContainsKey("choices"))continue;var choices=(IList)chunk["choices"];if(choices.Count==0)continue;
       var choice=(Dictionary<string,object>)choices[0];if(!choice.ContainsKey("delta"))continue;
       var delta=(Dictionary<string,object>)choice["delta"];if(delta.ContainsKey("content")&&delta["content"]!=null)output.Report(Convert.ToString(delta["content"]));
      }
     }
    }
   }
  }
  public void Stop() {
   Ready=false;LoadedModel=null;Metrics=null;
   if(process!=null){try{if(!process.HasExited){process.Kill();process.WaitForExit(3000);}}catch{}process.Dispose();process=null;}
   if(job!=null){job.Dispose();job=null;}if(client!=null){client.Dispose();client=null;}
  }
  public void Dispose(){Stop();}
 }
}
