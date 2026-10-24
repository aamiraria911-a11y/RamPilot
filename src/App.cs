using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Drawing;
using System.Windows.Forms;
using System.Threading;
using System.Threading.Tasks;
using System.Diagnostics;
using System.Collections.Generic;
using System.Reflection;

[assembly: AssemblyTitle("RamPilot")]
[assembly: AssemblyDescription("Local CPU AI with RAM-conscious model loading")]
[assembly: AssemblyVersion("2.1.0.0")]
[assembly: AssemblyCompany("RamPilot")]

namespace RamPilot {
 static class Program {
  [STAThread] static void Main(string[] args) {
   System.Net.ServicePointManager.SecurityProtocol=System.Net.SecurityProtocolType.Tls12;
   bool created;
   using(var mutex=new Mutex(true,"Local\\RamPilot.Desktop",out created)) {
    if(!created){MessageBox.Show("RamPilot is already running.","RamPilot");return;}
    Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
    try{Store.Initialize();Application.Run(new MainForm(args));}
    catch(Exception ex){MessageBox.Show(ex.Message,"RamPilot could not start",MessageBoxButtons.OK,MessageBoxIcon.Error);}
   }
  }
 }
 public sealed class MainForm:Form {
  static readonly Color Bg=Color.FromArgb(16,21,30),Surface=Color.FromArgb(24,31,43),PanelColor=Color.FromArgb(30,39,53),TextColor=Color.FromArgb(231,237,246),Muted=Color.FromArgb(157,173,193),Accent=Color.FromArgb(92,224,184);
  Settings settings;Engine engine=new Engine();List<ModelInfo> catalog;List<string> imports;List<Message> history;
  CancellationTokenSource operation;bool busy,closing;
  Panel content=new Panel();Panel chatPage,modelsPage,settingsPage;Label status,memory,modelTitle,modelDetails,profileText;
  RichTextBox transcript;TextBox prompt,systemPrompt;ListView modelList;ProgressBar progress;
  ComboBox mode;NumericUpDown context,threads,budget,maxTokens,temperature;CheckBox saveChat;
  Button loadButton,sendButton,stopButton,downloadButton,importButton,saveSettings,newButton;
  System.Windows.Forms.Timer monitor;
  public MainForm(string[] args) {
   settings=Store.Read("settings.json",new Settings());
   settings.Context=Math.Max(512,Math.Min(8192,settings.Context));settings.Threads=Math.Max(1,Math.Min(Environment.ProcessorCount,settings.Threads));
   settings.BudgetGiB=Math.Max(1,Math.Min(512,settings.BudgetGiB));settings.MaxTokens=Math.Max(32,Math.Min(4096,settings.MaxTokens));
   Guid conversationGuid;if(!string.IsNullOrEmpty(settings.ConversationId)&&!Guid.TryParseExact(settings.ConversationId,"N",out conversationGuid))settings.ConversationId="";
   settings.Mode="Layer streaming";if(double.IsNaN(settings.Temperature)||double.IsInfinity(settings.Temperature))settings.Temperature=0.7;settings.Temperature=Math.Max(0,Math.Min(2,settings.Temperature));
   imports=Store.Read("imports.json",new List<string>());history=settings.SaveChat?Store.Read("chat.json",new List<Message>()):new List<Message>();
   // Only complete turns are retained on disk. Reject malformed or oversized persisted histories.
   if(!ConversationStore.Valid(history))history=new List<Message>();
   if(imports==null)imports=new List<string>();imports=imports.Where(p=>!string.IsNullOrWhiteSpace(p)).ToList();
   catalog=Json.Decode<List<ModelInfo>>(File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"catalog.json")));
   Text="RamPilot · Local AI";Size=new Size(1160,800);MinimumSize=new Size(1000,700);StartPosition=FormStartPosition.CenterScreen;BackColor=Bg;ForeColor=TextColor;Font=new Font("Segoe UI",10);AutoScaleMode=AutoScaleMode.Dpi;
   try{Icon=new Icon(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"RamPilot.ico"));}catch{}
   var outer=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=2,RowCount=1,BackColor=Bg};outer.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,245));outer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));Controls.Add(outer);
   var sidebar=new TableLayoutPanel{Dock=DockStyle.Fill,BackColor=Surface,Padding=new Padding(20,28,20,20),ColumnCount=1,RowCount=10};
   foreach(int h in new[]{48,48,20,48,48,48,20})sidebar.RowStyles.Add(new RowStyle(SizeType.Absolute,h));sidebar.RowStyles.Add(new RowStyle(SizeType.Percent,100));sidebar.RowStyles.Add(new RowStyle(SizeType.Absolute,82));sidebar.RowStyles.Add(new RowStyle(SizeType.Absolute,60));
   var brand=Label("RamPilot 2.1",22,TextColor);sidebar.Controls.Add(brand,0,0);sidebar.Controls.Add(Label("LOCAL AI. YOUR MACHINE.",8,Accent),0,1);
   var chatNav=Button("Chat",()=>ShowPage(chatPage));var modelsNav=Button("Models",()=>ShowPage(modelsPage));var settingsNav=Button("Memory & settings",()=>ShowPage(settingsPage));
   sidebar.Controls.Add(chatNav,0,3);sidebar.Controls.Add(modelsNav,0,4);sidebar.Controls.Add(settingsNav,0,5);
   var note=Label("Explicit layer streaming\nLayer-by-layer on CPU\nNo account or API bill",10,Muted);sidebar.Controls.Add(note,0,8);
   var log=Button("Engine log",ShowLog);sidebar.Controls.Add(log,0,9);outer.Controls.Add(sidebar,0,0);
   var right=new TableLayoutPanel{Dock=DockStyle.Fill,Padding=new Padding(26,22,26,16),ColumnCount=1,RowCount=3};right.RowStyles.Add(new RowStyle(SizeType.Absolute,70));right.RowStyles.Add(new RowStyle(SizeType.Percent,100));right.RowStyles.Add(new RowStyle(SizeType.Absolute,55));
   var header=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=2,RowCount=1};header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,115));
   status=Label("Ready. Choose a model to get started.",11,TextColor);status.AccessibleName="App status";header.Controls.Add(status,0,0);
   stopButton=Button("Stop",Cancel);stopButton.Enabled=false;header.Controls.Add(stopButton,1,0);right.Controls.Add(header,0,0);
   content.Dock=DockStyle.Fill;right.Controls.Add(content,0,1);memory=Label("Reading system memory...",9,Muted);right.Controls.Add(memory,0,2);outer.Controls.Add(right,1,0);
   BuildChat();BuildModels();BuildSettings();RefreshModels();RefreshTranscript();ShowPage(chatPage);UpdateMemory();
   monitor=new System.Windows.Forms.Timer{Interval=1500};monitor.Tick+=async (s,e)=>{
    if(engine.Ready)await engine.RefreshMetricsAsync();
    UpdateMemory();if(engine.Ready&&!engine.Running){engine.Stop();loadButton.Text="Load selected model";SetStatus("The engine stopped. Check Engine log, then reload a smaller model.");}
   };monitor.Start();FormClosing+=OnClosing;
   if(args.Length>0&&args[0]=="--models")ShowPage(modelsPage);
   if(args.Length>0&&args[0]=="--settings")ShowPage(settingsPage);
   if(args.Length>0&&args[0]=="--smoke") {
    var t=new System.Windows.Forms.Timer{Interval=1000};t.Tick+=(s,e)=>{t.Stop();using(var bmp=new Bitmap(Width,Height)){DrawToBitmap(bmp,new Rectangle(0,0,Width,Height));bmp.Save(args.Length>1?args[1]:"smoke.png");}Close();};t.Start();
   }
  }
  Label Label(string text,float size,Color color){return new Label{Text=text,Dock=DockStyle.Fill,ForeColor=color,BackColor=Color.Transparent,Font=new Font("Segoe UI",size),TextAlign=ContentAlignment.MiddleLeft,UseMnemonic=false,AutoEllipsis=true,Margin=new Padding(0,0,0,4)};}
  Button Button(string text,Action action) {
   var b=new Button{Text=text,UseMnemonic=false,Dock=DockStyle.Fill,FlatStyle=FlatStyle.Flat,BackColor=PanelColor,ForeColor=TextColor,Cursor=Cursors.Hand,Margin=new Padding(0,4,8,4),Height=38,UseVisualStyleBackColor=false,AutoEllipsis=true};b.FlatAppearance.BorderSize=0;b.Click+=(s,e)=>{if(!closing)action();};return b;
  }
  void ShowPage(Panel page){foreach(Control c in content.Controls)c.Visible=c==page;page.BringToFront();}
  Panel Page(){var p=new Panel{Dock=DockStyle.Fill,BackColor=Bg,Visible=false};content.Controls.Add(p);return p;}
  FlowLayoutPanel Buttons(){return new FlowLayoutPanel{Dock=DockStyle.Fill,FlowDirection=FlowDirection.LeftToRight,WrapContents=false,BackColor=Bg};}
  void FixedButton(FlowLayoutPanel flow,Button button,int width){button.Dock=DockStyle.None;button.Width=width;flow.Controls.Add(button);}
  void BuildChat() {
   chatPage=Page();var layout=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=1,RowCount=6};
   layout.RowStyles.Add(new RowStyle(SizeType.Absolute,42));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,46));layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,27));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,95));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,47));chatPage.Controls.Add(layout);
   modelTitle=Label("Your private AI workspace",20,TextColor);layout.Controls.Add(modelTitle,0,0);
   var actions=Buttons();newButton=Button("New chat",NewChat);FixedButton(actions,newButton,115);FixedButton(actions,Button("Export chat",ExportChat),120);FixedButton(actions,Button("Choose model",()=>ShowPage(modelsPage)),135);FixedButton(actions,Button("Saved chats",OpenSavedChats),120);layout.Controls.Add(actions,0,1);
   transcript=new RichTextBox{Dock=DockStyle.Fill,ReadOnly=true,BackColor=Surface,ForeColor=TextColor,BorderStyle=BorderStyle.None,Font=new Font("Segoe UI",11),DetectUrls=false,WordWrap=true,Margin=new Padding(0,8,0,10)};transcript.AccessibleName="Chat transcript";layout.Controls.Add(transcript,0,2);
   layout.Controls.Add(Label("Enter to send · Shift+Enter for a new line · Responses are generated locally",9,Muted),0,3);
   prompt=new TextBox{Dock=DockStyle.Fill,Multiline=true,BackColor=PanelColor,ForeColor=TextColor,BorderStyle=BorderStyle.FixedSingle,Font=new Font("Segoe UI",11),ScrollBars=ScrollBars.Vertical,MaxLength=1000000};prompt.AccessibleName="Message";
   prompt.KeyDown+=(s,e)=>{if(e.KeyCode==Keys.Enter&&!e.Shift){e.SuppressKeyPress=true;if(!busy)Send();}};layout.Controls.Add(prompt,0,4);
   var bottom=Buttons();sendButton=Button("Send message",Send);sendButton.BackColor=Accent;sendButton.ForeColor=Bg;FixedButton(bottom,sendButton,160);FixedButton(bottom,Button("Unload model",Unload),130);layout.Controls.Add(bottom,0,5);
  }
  void BuildModels() {
   modelsPage=Page();var layout=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=1,RowCount=7};modelsPage.Controls.Add(layout);
   foreach(int h in new[]{43,56})layout.RowStyles.Add(new RowStyle(SizeType.Absolute,h));layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));foreach(int h in new[]{100,50,28,35})layout.RowStyles.Add(new RowStyle(SizeType.Absolute,h));
   layout.Controls.Add(Label("Find your model",20,TextColor),0,0);layout.Controls.Add(Label("Download a layer-streaming model, or import a local Qwen2/Llama SafeTensors folder. GGUF files are not used by this engine.",10,Muted),0,1);
   modelList=new ListView{Dock=DockStyle.Fill,View=View.Details,FullRowSelect=true,HideSelection=false,MultiSelect=false,BackColor=Surface,ForeColor=TextColor,BorderStyle=BorderStyle.None};modelList.Columns.Add("Model",235);modelList.Columns.Add("Download",95);modelList.Columns.Add("Status",135);modelList.Columns.Add("License",175);
   modelList.OwnerDraw=true;modelList.DrawColumnHeader+=(s,e)=>e.DrawDefault=true;modelList.DrawItem+=(s,e)=>{};
   modelList.DrawSubItem+=(s,e)=>{bool selected=e.Item.Selected;using(var brush=new SolidBrush(selected?Accent:Surface))e.Graphics.FillRectangle(brush,e.Bounds);var bounds=e.Bounds;bounds.X+=5;bounds.Width-=10;TextRenderer.DrawText(e.Graphics,e.SubItem.Text,modelList.Font,bounds,selected?Bg:TextColor,TextFormatFlags.EndEllipsis|TextFormatFlags.VerticalCenter|TextFormatFlags.NoPrefix);};modelList.SelectedIndexChanged+=(s,e)=>DescribeModel();layout.Controls.Add(modelList,0,2);
   modelDetails=Label("Choose a model above.",10,Muted);layout.Controls.Add(modelDetails,0,3);
   var buttons=Buttons();downloadButton=Button("Download / verify",Download);loadButton=Button("Load selected model",LoadSelected);importButton=Button("Import folder",Import);FixedButton(buttons,downloadButton,165);FixedButton(buttons,loadButton,175);FixedButton(buttons,importButton,120);FixedButton(buttons,Button("Model card",OpenModelCard),105);layout.Controls.Add(buttons,0,4);
   progress=new ProgressBar{Dock=DockStyle.Fill,Minimum=0,Maximum=1000,Height=14,Style=ProgressBarStyle.Continuous};layout.Controls.Add(progress,0,5);
   layout.Controls.Add(Label("Downloads use Hugging Face. Chat remains on your PC. Models have their own licenses.",9,Muted),0,6);
  }
  NumericUpDown Number(int min,int max,int value){return new NumericUpDown{Minimum=min,Maximum=max,Value=Math.Max(min,Math.Min(max,value)),Dock=DockStyle.Fill,BackColor=PanelColor,ForeColor=TextColor,BorderStyle=BorderStyle.FixedSingle,Margin=new Padding(0,8,0,8)};}
  void BuildSettings() {
   settingsPage=Page();settingsPage.AutoScroll=true;var layout=new TableLayoutPanel{Dock=DockStyle.Top,Height=720,MinimumSize=new Size(0,720),ColumnCount=2,RowCount=12};layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,200));layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));settingsPage.Controls.Add(layout);
   var title=Label("Memory & settings",20,TextColor);layout.Controls.Add(title,0,0);layout.SetColumnSpan(title,2);layout.RowStyles.Add(new RowStyle(SizeType.Absolute,48));
   mode=new ComboBox{DropDownStyle=ComboBoxStyle.DropDownList,Dock=DockStyle.Fill,BackColor=PanelColor,ForeColor=TextColor,Margin=new Padding(0,8,0,8)};mode.Items.AddRange(new object[]{"Layer streaming"});mode.SelectedItem=settings.Mode;
   context=Number(512,8192,settings.Context);context.Increment=512;threads=Number(1,Environment.ProcessorCount,settings.Threads);budget=Number(1,512,settings.BudgetGiB);maxTokens=Number(32,4096,settings.MaxTokens);maxTokens.Increment=32;temperature=Number(0,2,0);temperature.DecimalPlaces=1;temperature.Increment=0.1M;temperature.Value=(decimal)settings.Temperature;
   Control[] fields={mode,budget,context,threads,maxTokens,temperature};string[] labels={"Memory mode","Planning budget (GB)","Context (tokens)","CPU threads","Maximum reply tokens","Temperature (0 = greedy)"};
   for(int i=0;i<fields.Length;i++){layout.RowStyles.Add(new RowStyle(SizeType.Absolute,45));layout.Controls.Add(Label(labels[i],10,TextColor),0,i+1);layout.Controls.Add(fields[i],1,i+1);}
   profileText=Label("",10,Muted);layout.Controls.Add(profileText,0,7);layout.SetColumnSpan(profileText,2);layout.RowStyles.Add(new RowStyle(SizeType.Absolute,95));
   layout.Controls.Add(Label("System instructions",10,TextColor),0,8);systemPrompt=new TextBox{Dock=DockStyle.Fill,Multiline=true,ScrollBars=ScrollBars.Vertical,BackColor=PanelColor,ForeColor=TextColor,Text=settings.SystemPrompt,MaxLength=10000};layout.Controls.Add(systemPrompt,1,8);layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));
   saveChat=new CheckBox{Text="Save future conversations on this PC (plain JSON)",Checked=settings.SaveChat,Dock=DockStyle.Fill,ForeColor=Muted};layout.Controls.Add(saveChat,0,9);layout.SetColumnSpan(saveChat,2);layout.RowStyles.Add(new RowStyle(SizeType.Absolute,42));
   var actions=Buttons();saveSettings=Button("Save settings",SaveSettings);FixedButton(actions,saveSettings,140);FixedButton(actions,Button("Open data folder",()=>OpenPath(Store.Root)),160);FixedButton(actions,Button("Export diagnostics",ExportDiagnostics),165);layout.Controls.Add(actions,0,10);layout.SetColumnSpan(actions,2);layout.RowStyles.Add(new RowStyle(SizeType.Absolute,47));
   var note=Label("Settings apply after reloading. Loads one decoder block, computes it on CPU, then releases its weights. Runtime and KV cache also use RAM.",9,Muted);layout.Controls.Add(note,0,11);layout.SetColumnSpan(note,2);layout.RowStyles.Add(new RowStyle(SizeType.Absolute,48));
   mode.SelectedIndexChanged+=(s,e)=>DescribeProfile();budget.ValueChanged+=(s,e)=>DescribeProfile();context.ValueChanged+=(s,e)=>DescribeProfile();DescribeProfile();
  }
  void DescribeProfile() {
   profileText.Text="Each decoder block is read from disk, computed, and released before the next. Embedding and output matrices are processed in row chunks. Budget checks include runtime and KV cache; they are not an OS hard cap. An SSD is strongly preferred.";

  }
  void SetStatus(string text){if(!closing&&!IsDisposed)status.Text=text;}
  void SetBusy(bool value) {
   if(closing)return;busy=value;stopButton.Enabled=value;sendButton.Enabled=!value;loadButton.Enabled=!value;downloadButton.Enabled=!value;importButton.Enabled=!value;saveSettings.Enabled=!value;newButton.Enabled=!value;modelList.Enabled=!value;prompt.ReadOnly=value;
   if(!value){if(operation!=null)operation.Dispose();operation=null;}
  }
  void StartOperation(){operation=new CancellationTokenSource();SetBusy(true);}
  void Cancel(){if(operation!=null){SetStatus("Stopping...");operation.Cancel();}}
  void UpdateMemory(){var m=MemoryInfo.Read();memory.Text="SYSTEM RAM   "+MemoryInfo.GiB(m.Available)+" available / "+MemoryInfo.GiB(m.Total)+" total   •   ENGINE "+MemoryInfo.GiB(engine.WorkingSet)+"   •   "+(engine.Metrics!=null&&engine.Metrics.ContainsKey("current_group")?Convert.ToString(engine.Metrics["current_group"])+" | live blocks "+Convert.ToString(engine.Metrics["live_weight_groups"]):"LAYER STREAMING");}
  void RefreshModels() {
   string selected=settings.ModelPath;modelList.Items.Clear();
   foreach(var m in catalog){string path=Path.Combine(Store.Models,m.FileName);var item=new ListViewItem(m.Name);item.SubItems.Add(MemoryInfo.GiB(m.Bytes));item.SubItems.Add(File.Exists(path)?"Ready":Directory.Exists(Path.Combine(Store.Models,m.DirectoryName))?"Partial download":"Not downloaded");item.SubItems.Add(m.License);item.Tag=m;modelList.Items.Add(item);if(path==selected)item.Selected=true;}
   foreach(string path in imports.Distinct(StringComparer.OrdinalIgnoreCase).Where(p=>p.EndsWith(".stream.json",StringComparison.OrdinalIgnoreCase))) {
    if(catalog.Any(m=>Path.Combine(Store.Models,m.FileName).Equals(path,StringComparison.OrdinalIgnoreCase)))continue;
    var item=new ListViewItem(Path.GetFileName(path));item.SubItems.Add(File.Exists(path)?MemoryInfo.GiB(new FileInfo(path).Length):"?");item.SubItems.Add(File.Exists(path)?"Imported":"Missing");item.SubItems.Add("Check model card");item.Tag=path;modelList.Items.Add(item);if(path==selected)item.Selected=true;
   }
   if(modelList.SelectedItems.Count==0&&modelList.Items.Count>0)modelList.Items[0].Selected=true;DescribeModel();
  }
  object Selected(){return modelList.SelectedItems.Count==0?null:modelList.SelectedItems[0].Tag;}
  string SelectedPath(){var value=Selected();var m=value as ModelInfo;return m!=null?Path.Combine(Store.Models,m.FileName):value as string;}
  void DescribeModel(){var value=Selected();var m=value as ModelInfo;string path=SelectedPath();if(m!=null)modelDetails.Text=m.Description+"\n"+m.License+" · SHA-256 verified download · "+MemoryInfo.GiB(m.Bytes)+" on disk\n"+(File.Exists(path)?"Ready to load. ":"Click Download, then Load selected model. ")+"One decoder block is loaded at a time; runtime and KV cache also use RAM.";else modelDetails.Text=path==null?"Choose a model above.":"Imported model: "+path+"\nOnly import files from a source you trust. Compatibility depends on the model architecture.";}
  async void Download() {
   if(busy)return;var model=Selected() as ModelInfo;if(model==null){SetStatus("Choose a catalog model to download, or load your imported model folder.");return;}
   string path=Path.Combine(Store.Models,model.FileName);
   try {
    var drive=new DriveInfo(Path.GetPathRoot(Store.Models));long remaining=ModelInstaller.Remaining(model);
    if(drive.AvailableFreeSpace<remaining+256*1024*1024)throw new IOException("There is not enough free disk space for this model.");
    StartOperation();engine.Stop();SetStatus("Checking files and connecting to Hugging Face...");
    await ModelInstaller.FetchAsync(model,new Progress<DownloadProgress>(p=>{if(closing)return;progress.Value=(int)Math.Max(0,Math.Min(1000,(double)p.Done/p.Total*1000));SetStatus(p.Stage+" · "+MemoryInfo.GiB(p.Done)+" / "+MemoryInfo.GiB(p.Total));}),operation.Token);
    settings.ModelPath=path;Store.Write("settings.json",settings);SetStatus("Download verified. Click Load selected model.");
   }catch(OperationCanceledException){SetStatus("Download paused. Click Download / resume to continue.");}
   catch(Exception ex){if(operation!=null&&operation.IsCancellationRequested)SetStatus("Download paused. Click Download / resume to continue.");else Error(ex);}
   finally{SetBusy(false);RefreshModels();}
  }
  void Import() {
   if(busy)return;using(var dialog=new FolderBrowserDialog{Description="Choose a dense Qwen2/Qwen2.5 or Llama folder containing config.json, tokenizer files and model*.safetensors",ShowNewFolderButton=false}) {
    if(dialog.ShowDialog()!=DialogResult.OK)return;
    try{string config=Path.Combine(dialog.SelectedPath,"config.json");if(!File.Exists(config)||Directory.GetFiles(dialog.SelectedPath,"model*.safetensors").Length==0)throw new IOException("This folder needs config.json and complete model SafeTensors files.");var cfg=Json.Object(File.ReadAllText(config));string type=Convert.ToString(cfg["model_type"]);if(type!="qwen2"&&type!="llama")throw new IOException("This build supports dense Qwen2/Qwen2.5 and Llama models.");string manifest=Path.Combine(Store.Models,"import-"+Guid.NewGuid().ToString("N")+".stream.json");File.WriteAllText(manifest,Json.Encode(new{format="rampilot-safetensors-v1",model_dir=dialog.SelectedPath}));imports.Add(manifest);settings.ModelPath=manifest;Store.Write("imports.json",imports);Store.Write("settings.json",settings);RefreshModels();SetStatus("Model folder added by reference. Click Load selected model.");}catch(Exception ex){Error(ex);}
   }
  }

  async void LoadSelected() {
   if(busy)return;string path=SelectedPath();if(string.IsNullOrEmpty(path)){SetStatus("Select a model first.");return;}
   if(!File.Exists(path)){SetStatus("Download this model first.");return;}
   try {StartOperation();SetStatus("Starting CPU engine...");await engine.StartAsync(path,settings,new Progress<string>(SetStatus),operation.Token);settings.ModelPath=path;Store.Write("settings.json",settings);modelTitle.Text=Path.GetFileNameWithoutExtension(path);SetStatus("Model ready · "+settings.Mode+" · "+engine.Context+" token context");ShowPage(chatPage);}
   catch(OperationCanceledException){SetStatus("Model loading cancelled.");}
   catch(Exception ex){Error(ex);}finally{SetBusy(false);UpdateMemory();}
  }
  void Unload(){if(busy)return;engine.Stop();modelTitle.Text="Your private AI workspace";SetStatus("Model unloaded. Live weights and KV cache released.");UpdateMemory();}
  async void Send() {
   if(busy)return;string user=prompt.Text.Trim();if(user.Length==0)return;if(!engine.Ready){SetStatus("Choose Models, download or import a SafeTensors model folder, then load it first.");ShowPage(modelsPage);return;}
   var answer=new StringBuilder();bool started=false;
   try {
    StartOperation();SetStatus("Preparing conversation...");var request=new List<Message>{new Message("system",settings.SystemPrompt)};request.AddRange(history);request.Add(new Message("user",user));
    int reply=Math.Min(settings.MaxTokens,Math.Max(32,engine.Context/2));
    request=await engine.FitAsync(request,reply,new Progress<string>(SetStatus),operation.Token);operation.Token.ThrowIfCancellationRequested();
    prompt.Clear();Append("YOU\n",Accent);Append(user+"\n\n",TextColor);Append("ASSISTANT\n",Accent);started=true;
    SetStatus("Generating on CPU... large models may take time.");var watch=Stopwatch.StartNew();
    await engine.GenerateAsync(request,reply,settings.Temperature,new Progress<string>(delta=>{if(closing||!busy)return;answer.Append(delta);Append(delta,TextColor);}),operation.Token);
    // Drain posted progress callbacks before persisting the completed turn.
    await Task.Yield();history.Add(new Message("user",user));history.Add(new Message("assistant",answer.ToString()));SaveConversation();await engine.RefreshMetricsAsync();
    Append("\n\n",TextColor);SetStatus("Finished in "+watch.Elapsed.TotalSeconds.ToString("0.0")+" seconds"+(engine.Metrics!=null&&engine.Metrics.ContainsKey("tokens_per_second")?" · "+Convert.ToDouble(engine.Metrics["tokens_per_second"]).ToString("0.00")+" tok/s including prompt":"")+" · weights released");
   }catch(OperationCanceledException){if(started)Append("\n[Stopped. This turn was not saved.]\n\n",Muted);prompt.Text=user;SetStatus("Generation stopped.");}
   catch(Exception ex){if(operation!=null&&operation.IsCancellationRequested){if(started)Append("\n[Stopped. This turn was not saved.]\n\n",Muted);SetStatus("Generation stopped.");}else{if(started)Append("\n[The answer did not finish. This turn was not saved.]\n\n",Muted);Error(ex);}prompt.Text=user;}
   finally{SetBusy(false);prompt.Focus();}
  }
  void Append(string text,Color color){if(closing||transcript.IsDisposed)return;transcript.SelectionStart=transcript.TextLength;transcript.SelectionLength=0;transcript.SelectionColor=color;transcript.AppendText(text);transcript.ScrollToCaret();}
  void RefreshTranscript(){transcript.Clear();if(history.Count==0){Append("Welcome to RamPilot\n\n",Accent);Append("1. Open Models and download a small model, or import a SafeTensors model folder.\n2. Load it, then type your message here.\n\nYour model runs on your CPU. No account or cloud API is needed.\nUse Memory & settings to adjust context size and streaming budget.\n\n",Muted);}else foreach(var m in history){Append(m.role=="user"?"YOU\n":"ASSISTANT\n",Accent);Append(m.content+"\n\n",TextColor);}}
  void SaveConversation(){if(!settings.SaveChat)return;if(history.Count>1000)history=history.Skip(history.Count-1000).ToList();Store.Write("chat.json",history);if(history.Count>0)settings.ConversationId=ConversationStore.Save(settings.ConversationId,history);Store.Write("settings.json",settings);}
  void NewChat(){if(busy)return;try{SaveConversation();history.Clear();settings.ConversationId="";Store.Write("settings.json",settings);if(File.Exists(Path.Combine(Store.Root,"chat.json")))File.Delete(Path.Combine(Store.Root,"chat.json"));RefreshTranscript();SetStatus("New conversation. Previous saved chats are available in Saved chats.");}catch(Exception ex){Error(ex);}}
  void OpenSavedChats(){
   if(busy)return;
   using(var form=new Form{Text="Saved conversations",Size=new Size(700,500),StartPosition=FormStartPosition.CenterParent,BackColor=Bg,ForeColor=TextColor}){
    var layout=new TableLayoutPanel{Dock=DockStyle.Fill,Padding=new Padding(16),RowCount=3,ColumnCount=1};layout.RowStyles.Add(new RowStyle(SizeType.Absolute,38));layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));layout.RowStyles.Add(new RowStyle(SizeType.Absolute,45));form.Controls.Add(layout);
    var search=new TextBox{Dock=DockStyle.Fill,BackColor=Surface,ForeColor=TextColor};var list=new ListBox{Dock=DockStyle.Fill,BackColor=Surface,ForeColor=TextColor,Font=Font};layout.Controls.Add(search,0,0);layout.Controls.Add(list,0,1);
    var all=ConversationStore.List();Action refresh=()=>{list.Items.Clear();foreach(var chat in all.Where(c=>c.Title.IndexOf(search.Text,StringComparison.OrdinalIgnoreCase)>=0))list.Items.Add(chat);};refresh();search.TextChanged+=(s,e)=>refresh();
    Action open=()=>{var chat=list.SelectedItem as SavedConversation;if(chat==null)return;try{SaveConversation();var saved=ConversationStore.Load(chat.Id);history=saved.Messages;settings.ConversationId=saved.Id;SaveConversation();RefreshTranscript();SetStatus("Opened "+saved.Title);form.Close();}catch(Exception ex){Error(ex);}};
    list.DoubleClick+=(s,e)=>open();var button=Button("Open selected conversation",open);layout.Controls.Add(button,0,2);form.ShowDialog(this);
   }
  }
  void ExportDiagnostics(){using(var dialog=new SaveFileDialog{FileName="RamPilot-diagnostics.json",Filter="JSON (*.json)|*.json"})if(dialog.ShowDialog()==DialogResult.OK)try{var info=MemoryInfo.Read();File.WriteAllText(dialog.FileName,Json.Encode(new{app="RamPilot",version="2.1.0",os=Environment.OSVersion.VersionString,cpu_count=Environment.ProcessorCount,process_64_bit=Environment.Is64BitProcess,total_ram_bytes=info.Total,available_ram_bytes=info.Available,context=settings.Context,budget_gib=settings.BudgetGiB,max_tokens=settings.MaxTokens,temperature=settings.Temperature,engine=engine.Metrics}),Encoding.UTF8);SetStatus("Diagnostics exported. No chat text, usernames, model paths or session keys included.");}catch(Exception ex){Error(ex);}}
  void ExportChat(){if(history.Count==0){SetStatus("There is no completed conversation to export yet.");return;}using(var dialog=new SaveFileDialog{FileName="RamPilot-chat.txt",Filter="Text file (*.txt)|*.txt"})if(dialog.ShowDialog()==DialogResult.OK)try{File.WriteAllText(dialog.FileName,string.Join("\r\n\r\n",history.Select(m=>m.role.ToUpperInvariant()+"\r\n"+m.content)),Encoding.UTF8);SetStatus("Chat exported.");}catch(Exception ex){Error(ex);}}
  void SaveSettings(){if(busy)return;try{settings.Mode=Convert.ToString(mode.SelectedItem);settings.Context=(int)context.Value;settings.Threads=(int)threads.Value;settings.BudgetGiB=(int)budget.Value;settings.MaxTokens=(int)maxTokens.Value;settings.Temperature=(double)temperature.Value;settings.SystemPrompt=systemPrompt.Text;settings.SaveChat=saveChat.Checked;Store.Write("settings.json",settings);if(!settings.SaveChat&&File.Exists(Path.Combine(Store.Root,"chat.json")))File.Delete(Path.Combine(Store.Root,"chat.json"));else if(settings.SaveChat)SaveConversation();engine.Stop();modelTitle.Text="Your private AI workspace";SetStatus("Settings saved. Load your model to apply them.");}catch(Exception ex){Error(ex);}}
  void OpenModelCard(){var m=Selected() as ModelInfo;if(m!=null)OpenPath(m.Page);else SetStatus("Use the original model source to check the license and model card.");}
  void OpenPath(string path){try{Process.Start(new ProcessStartInfo(path){UseShellExecute=true});}catch(Exception ex){Error(ex);}}
  void ShowLog(){var form=new Form{Text="RamPilot · Engine log",Size=new Size(850,560),StartPosition=FormStartPosition.CenterParent,BackColor=Bg};var box=new TextBox{Multiline=true,ReadOnly=true,Dock=DockStyle.Fill,ScrollBars=ScrollBars.Both,WordWrap=false,BackColor=Surface,ForeColor=TextColor,Font=new Font("Consolas",10),Text=engine.LogTail};form.Controls.Add(box);form.ShowDialog(this);form.Dispose();}
  void Error(Exception ex){SetStatus("Something needs attention. See the message for details.");if(!closing)MessageBox.Show(this,ex.Message.Length>6000?ex.Message.Substring(0,6000):ex.Message,"RamPilot",MessageBoxButtons.OK,MessageBoxIcon.Information);}
  void OnClosing(object sender,FormClosingEventArgs e){closing=true;if(monitor!=null)monitor.Stop();if(operation!=null)operation.Cancel();engine.Dispose();}
 }
}
