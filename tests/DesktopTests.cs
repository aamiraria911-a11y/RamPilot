using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading;
using System.Threading.Tasks;
using System.Security.Cryptography;
using System.Collections.Generic;
using RamPilot;
class DesktopTests {
 static int checks=0;
 static void Check(bool value,string message){checks++;if(!value)throw new Exception(message);}
 class Immediate:IProgress<DownloadProgress>{public void Report(DownloadProgress p){}}
 class DownloadHandler:HttpMessageHandler {
  readonly byte[] payload;readonly bool badRange;
  public DownloadHandler(byte[] bytes,bool invalid=false){payload=bytes;badRange=invalid;}
  protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken ct){
   long offset=request.Headers.Range==null?0:request.Headers.Range.Ranges.First().From.Value;
   var response=new HttpResponseMessage(offset>0?HttpStatusCode.PartialContent:HttpStatusCode.OK){RequestMessage=request,Content=new ByteArrayContent(payload.Skip((int)offset).ToArray())};
   if(offset>0)response.Content.Headers.ContentRange=new ContentRangeHeaderValue(badRange?0:offset,payload.Length-1,payload.Length);
   return Task.FromResult(response);
  }
 }
 static string Hash(byte[] payload){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(payload)).Replace("-","").ToLowerInvariant();}
 static async Task Run(){
  string root=Path.Combine(Path.GetTempPath(),"rampilot-test-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);Store.Root=root;Store.Initialize();
  try{
   var messages=new List<Message>{new Message("user","Hello سلام"),new Message("assistant","Hi")};
   string id=ConversationStore.Save("",messages);Check(ConversationStore.Load(id).Messages[0].content==messages[0].content,"Unicode session round-trip");
   Check(ConversationStore.Save(id,messages)==id,"Stable session identity");Check(ConversationStore.List().Count==1,"No duplicate sessions");
   bool rejected=false;try{ConversationStore.Load("../outside");}catch(IOException){rejected=true;}Check(rejected,"Reject traversal identifier");
   File.WriteAllText(Path.Combine(root,"Conversations",Guid.NewGuid().ToString("N")+".json"),"null");Check(ConversationStore.List().Count==1,"Skip corrupt session");
   Check(!ConversationStore.Valid(new List<Message>{new Message("user","partial")}),"Partial turns not saved");
   var bytes=System.Text.Encoding.UTF8.GetBytes("verified fixture payload");
   var model=new ModelInfo{Name="Fixture",DirectoryName="fixture",FileName="fixture.stream.json",Bytes=bytes.Length,Files=new List<ModelFile>{new ModelFile{Name="model.bin",Url="https://fixture.invalid/model.bin",Bytes=bytes.Length,Sha256=Hash(bytes)}}};
   string folder=Path.Combine(Store.Models,model.DirectoryName);Directory.CreateDirectory(folder);string path=Path.Combine(folder,"model.bin");
   File.WriteAllBytes(path+".part",bytes.Take(4).ToArray());
   await ModelInstaller.FetchAsync(model,new Immediate(),CancellationToken.None,()=>new DownloadHandler(bytes));
   Check(File.ReadAllBytes(path).SequenceEqual(bytes),"Resume and verify payload");Check(File.Exists(Path.Combine(Store.Models,model.FileName)),"Verified ready marker");
   File.WriteAllText(path,"damaged");
   await ModelInstaller.FetchAsync(model,new Immediate(),CancellationToken.None,()=>new DownloadHandler(bytes));
   Check(Directory.GetFiles(folder,"*.corrupt-*").Length==1,"Preserve damaged original");Check(File.ReadAllBytes(path).SequenceEqual(bytes),"Repair replacement");
   File.Delete(path);File.WriteAllBytes(path+".part",bytes.Take(4).ToArray());rejected=false;
   try{await ModelInstaller.FetchAsync(model,new Immediate(),CancellationToken.None,()=>new DownloadHandler(bytes,true));}catch(IOException){rejected=true;}
   Check(rejected,"Reject incorrect range");Check(!File.Exists(Path.Combine(Store.Models,model.FileName)),"Failed repair invalidates ready marker");
   Console.WriteLine("PASS: "+checks+" desktop session/download checks");
  }finally{Directory.Delete(root,true);}
 }
 static int Main(){try{Run().GetAwaiter().GetResult();return 0;}catch(Exception ex){Console.Error.WriteLine(ex);return 1;}}
}
