using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;

namespace RamPilot {
 public sealed class SavedConversation {
  public string Id {get;set;}
  public string Title {get;set;}
  public string Updated {get;set;}
  public List<Message> Messages {get;set;}
  public override string ToString(){return Title+"  ·  "+(Messages.Count/2)+" turns";}
 }
 public static class ConversationStore {
  static string Folder {get{return Path.Combine(Store.Root,"Conversations");}}
  static string PathFor(string id){Guid parsed;if(!Guid.TryParseExact(id,"N",out parsed))throw new IOException("Invalid conversation identifier.");return Path.Combine(Folder,id+".json");}
  public static bool Valid(List<Message> messages){return messages!=null&&messages.Count<=1000&&messages.Count%2==0&&!messages.Where((m,i)=>m==null||m.role!=(i%2==0?"user":"assistant")||m.content==null||m.content.Length>1000000).Any();}
  public static string Save(string id,List<Message> messages) {
   if(!Valid(messages)||messages.Count==0)throw new IOException("Only complete conversations can be saved.");
   if(string.IsNullOrEmpty(id))id=Guid.NewGuid().ToString("N");
   Directory.CreateDirectory(Folder);string path=PathFor(id),tmp=path+".tmp";
   var title=messages[0].content.Trim().Split('\n')[0];if(title.Length==0)title="Untitled chat";if(title.Length>80)title=title.Substring(0,80);
   var value=new SavedConversation{Id=id,Title=title,Updated=DateTime.UtcNow.ToString("o"),Messages=messages};
   File.WriteAllText(tmp,Json.Encode(value),new System.Text.UTF8Encoding(false));if(File.Exists(path))File.Replace(tmp,path,null);else File.Move(tmp,path);
   return id;
  }
  public static SavedConversation Load(string id) {
   string path=PathFor(id);if(new FileInfo(path).Length>16777216)throw new IOException("This saved chat is too large.");
   var value=Json.Decode<SavedConversation>(File.ReadAllText(path));
   if(value==null||value.Id!=id||!Valid(value.Messages))throw new IOException("This conversation is damaged or unavailable.");
   if(string.IsNullOrWhiteSpace(value.Title))value.Title="Untitled chat";return value;
  }
  public static List<SavedConversation> List() {
   var result=new List<SavedConversation>();if(!Directory.Exists(Folder))return result;
   foreach(string path in Directory.GetFiles(Folder,"*.json")){try{result.Add(Load(Path.GetFileNameWithoutExtension(path)));}catch{}}
   return result.OrderByDescending(x=>x.Updated,StringComparer.Ordinal).ToList();
  }
 }
}
