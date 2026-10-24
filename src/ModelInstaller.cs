using System;
using System.IO;
using System.Net.Http;
using System.Linq;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace RamPilot {
 public class ModelFile {public string Name{get;set;}public string Url{get;set;}public string Sha256{get;set;}public long Bytes{get;set;}}
 public static class ModelInstaller {
  static string Folder(ModelInfo m){if(Path.GetFileName(m.DirectoryName)!=m.DirectoryName)throw new IOException("Invalid model directory.");return Path.Combine(Store.Models,m.DirectoryName);}
  public static long Remaining(ModelInfo m){string folder=Folder(m);return m.Files.Sum(f=>Math.Max(0,f.Bytes-(File.Exists(Path.Combine(folder,f.Name))?new FileInfo(Path.Combine(folder,f.Name)).Length:File.Exists(Path.Combine(folder,f.Name)+".part")?new FileInfo(Path.Combine(folder,f.Name)+".part").Length:0)));}
  public static async Task FetchAsync(ModelInfo model,IProgress<DownloadProgress> progress,CancellationToken ct,Func<HttpMessageHandler> handlerFactory=null) {
   string folder=Folder(model);Directory.CreateDirectory(folder);long complete=0;
   string manifest=Path.Combine(Store.Models,model.FileName);if(Path.GetFileName(model.FileName)!=model.FileName)throw new IOException("Invalid manifest filename.");if(File.Exists(manifest))File.Delete(manifest);
   foreach(var file in model.Files) {
    ct.ThrowIfCancellationRequested();if(Path.GetFileName(file.Name)!=file.Name)throw new IOException("Invalid model filename.");string path=Path.Combine(folder,file.Name);
    if(File.Exists(path)) {
     progress.Report(new DownloadProgress{Done=complete,Total=model.Bytes,Stage="Checking "+file.Name});
     bool valid=await Task.Run(()=>{using(var sha=SHA256.Create())using(var stream=File.OpenRead(path)){var buffer=new byte[1048576];int n;while((n=stream.Read(buffer,0,buffer.Length))>0){ct.ThrowIfCancellationRequested();sha.TransformBlock(buffer,0,n,null,0);}sha.TransformFinalBlock(new byte[0],0,0);return BitConverter.ToString(sha.Hash).Replace("-","").Equals(file.Sha256,StringComparison.OrdinalIgnoreCase);}},ct);
     if(!valid){File.Move(path,path+".corrupt-"+Guid.NewGuid().ToString("N").Substring(0,8));progress.Report(new DownloadProgress{Done=complete,Total=model.Bytes,Stage="Kept damaged file; downloading replacement"});}
    }
    if(!File.Exists(path)) {
     long partial=File.Exists(path+".part")?Math.Min(file.Bytes,new FileInfo(path+".part").Length):0;var drive=new DriveInfo(Path.GetPathRoot(folder));if(drive.AvailableFreeSpace<file.Bytes-partial+256L*1048576)throw new IOException("Not enough disk space. Damaged files are preserved as .corrupt-*; remove them if no longer needed.");
     long before=complete;
     await Downloader.FetchAsync(new ModelInfo{FileName=file.Name,Url=file.Url,Bytes=file.Bytes,Sha256=file.Sha256},path,new Progress<DownloadProgress>(p=>progress.Report(new DownloadProgress{Done=before+p.Done,Total=model.Bytes,Stage=p.Stage+" · "+file.Name})),ct,handlerFactory==null?null:handlerFactory(),false);
    }
    complete+=file.Bytes;
   }
   ct.ThrowIfCancellationRequested();
   string temp=manifest+".tmp";
   File.WriteAllText(temp,Json.Encode(new{format="rampilot-safetensors-v1",model_dir=model.DirectoryName,repo=model.Repo,revision=model.Revision}),new UTF8Encoding(false));
   if(File.Exists(manifest))File.Replace(temp,manifest,null);else File.Move(temp,manifest);
  }
 }
}
