using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using RamPilot;
class Inline<T>:IProgress<T>{readonly Action<T> action;public Inline(Action<T> a){action=a;}public void Report(T v){action(v);}}
class Tests {
 static void Check(bool condition,string text){if(!condition)throw new Exception("FAIL: "+text);Console.WriteLine("PASS: "+text);}
 static System.Net.Http.HttpMessageHandler LegacyHandler(){
  // Mono's default socket transport cannot enumerate interfaces in this host.
  // Use Mono's legacy HTTP transport for Linux integration tests only.
  if(Environment.OSVersion.Platform==PlatformID.Win32NT)return new System.Net.Http.HttpClientHandler{UseProxy=false};
  var assembly=typeof(System.Net.Http.HttpClient).Assembly;
  var legacy=Activator.CreateInstance(assembly.GetType("System.Net.Http.MonoWebRequestHandler"),true);
  var type=assembly.GetType("System.Net.Http.IMonoHttpClientHandler");
  var ctor=typeof(System.Net.Http.HttpClientHandler).GetConstructor(System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic,null,new[]{type},null);
  var handler=(System.Net.Http.HttpClientHandler)ctor.Invoke(new[]{legacy});handler.UseProxy=false;return handler;
 }
 static int Main(string[] args){try{AppContext.SetSwitch("System.Net.Http.UseSocketsHttpHandler",false);Run(args).GetAwaiter().GetResult();return 0;}catch(Exception e){Console.Error.WriteLine(e);return 1;}}
 static async Task Run(string[] args){
  string root=Path.GetFullPath(args[0]);Store.Root=Path.Combine(root,"tests","data");Store.Initialize();
  Store.Write("test.json",new Settings{Context=1024});Store.Write("test.json",new Settings{Context=2048});Check(Store.Read("test.json",new Settings()).Context==2048,"atomic settings replacement");
  var settings=new Settings{Context=512,Threads=2,Mode="Layer streaming",BudgetGiB=1};
  Check(RunProfile.Quote("C:\\models with spaces\\model.stream.json").StartsWith("\"C:"),"Windows argument quoting");
  using(var engine=new Engine(LegacyHandler){Executable=(args.Length>1?args[1]:Path.Combine(root,"build","engine","python","python.exe")),BackendScript=Path.Combine(root,"backend","server.py")}){
   using(var loadTimeout=new CancellationTokenSource(45000)) { try { await engine.StartAsync(Path.Combine(root,"tests","real-model","real.stream.json"),settings,new Inline<string>(Console.WriteLine),loadTimeout.Token); } catch { Console.WriteLine(engine.LogTail);throw; } }
   Check(engine.Ready&&engine.Running,"real layer-streaming model load");
   var messages=new List<Message>{new Message("system","Be helpful."),new Message("user","Tell a short story.")};
   Check(await engine.CountTokensAsync(messages,CancellationToken.None)>0,"chat template and token counting");
   var text="";await engine.GenerateAsync(messages,4,new Inline<string>(s=>text+=s),CancellationToken.None);Check(text.Length>0,"real streamed model generation");
   var longHistory=new List<Message>{messages[0],new Message("user",string.Join(" ",Enumerable.Repeat("hello",500))),new Message("assistant","old reply"),messages[1]};
   var fit=await engine.FitAsync(longHistory,32,new Inline<string>(Console.WriteLine),CancellationToken.None);Check(fit.Count==2&&fit[1].content==messages[1].content,"old turns trimmed while preserving current question");
   bool oversized=false;try{await engine.FitAsync(new List<Message>{messages[0],longHistory[1]},64,new Inline<string>(s=>{}),CancellationToken.None);}catch(IOException){oversized=true;}Check(oversized,"oversized current question rejected");
   using(var stop=new CancellationTokenSource()){
    bool cancelled=false;try{await engine.GenerateAsync(messages,128,new Inline<string>(s=>stop.Cancel()),stop.Token);}catch(OperationCanceledException){cancelled=true;}Check(cancelled,"stream cancellation");
   }
   await engine.RefreshMetricsAsync();
   Check(Convert.ToInt32(engine.Metrics["peak_live_weight_groups"])==1,"server reports only one live weight group");
   engine.Stop();Check(!engine.Ready&&!engine.Running,"engine unload and child cleanup");
  }
  using(var engine=new Engine(LegacyHandler){Executable=(args.Length>1?args[1]:Path.Combine(root,"build","engine","python","python.exe")),BackendScript=Path.Combine(root,"backend","server.py")}){
   using(var stop=new CancellationTokenSource()){stop.Cancel();bool cancelled=false;try{await engine.StartAsync(Path.Combine(root,"tests","real-model","real.stream.json"),settings,new Inline<string>(s=>{}),stop.Token);}catch(OperationCanceledException){cancelled=true;}Check(cancelled&&!engine.Running,"cancelled model load leaves no process");}
  }
 }
}
