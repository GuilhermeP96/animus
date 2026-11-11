// Read-only WebView2 renderer. Markdown never receives a native host object.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Xml;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AnimusDesktop {
    class MarkdownPreview : UserControl {
        const string Host="animus-preview.invalid";
        readonly string data,assets;
        readonly WebView2 web;
        readonly Label warning;
        readonly JavaScriptSerializer json=new JavaScriptSerializer {MaxJsonLength=4*1024*1024};
        readonly HashSet<string> resources=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        static bool loaderReady;
        bool initializing,ready;
        int documentId;
        string markdown="",vault="",path="",fragment="";
        public int BlockedRequests;
        public Dictionary<string,object> LastMetrics=new Dictionary<string,object>();
        public event Action<string,string,string,string> NoteRequested;
        public event Action<int,string,string,string,string> ImageRequested;
        public event Action ExpandRequested;

        public MarkdownPreview(string directory) {
            string application=Path.GetDirectoryName(typeof(MarkdownPreview).Assembly.Location);
            data=directory;assets=Path.Combine(application,"preview");
            BackColor=Brand.Surface;
            if(!loaderReady) {
                string arch=Environment.GetEnvironmentVariable("PROCESSOR_ARCHITECTURE")=="ARM64"?"win-arm64":IntPtr.Size==8?"win-x64":"win-x86";
                CoreWebView2Environment.SetLoaderDllFolderPath(Path.Combine(application,"runtimes",arch,"native"));loaderReady=true;
            }
            web=new WebView2 {Dock=DockStyle.Fill,DefaultBackgroundColor=Brand.Surface,AccessibleName="Leitura Markdown, diagramas e objetos interativos"};
            warning=new Label {Dock=DockStyle.Fill,ForeColor=Brand.Muted,BackColor=Brand.Surface,Padding=new Padding(18),Text="Preparando a leitura…"};
            Controls.Add(web);Controls.Add(warning);
            VisibleChanged+=(o,e)=>{if(Visible&&!ready&&!initializing)Initialize();};
        }
        static string Value(Dictionary<string,object> obj,string key) {object value;return obj.TryGetValue(key,out value)&&value!=null?Convert.ToString(value):"";}
        async void Initialize() {
            if(initializing||ready||IsDisposed)return;initializing=true;
            try {
                if(!Directory.Exists(assets))throw new IOException();
                foreach(string file in Directory.GetFiles(assets,"*",SearchOption.AllDirectories))resources.Add("/"+file.Substring(assets.Length+1).Replace('\\','/'));
                CoreWebView2Environment environment=await CoreWebView2Environment.CreateAsync(null,Path.Combine(data,"preview-cache"));
                if(IsDisposed)return;
                await web.EnsureCoreWebView2Async(environment);
                CoreWebView2 core=web.CoreWebView2;
                core.Settings.AreHostObjectsAllowed=false;core.Settings.AreDevToolsEnabled=false;
                core.Settings.AreDefaultContextMenusEnabled=false;core.Settings.AreDefaultScriptDialogsEnabled=false;
                core.Settings.IsStatusBarEnabled=false;core.Settings.AreBrowserAcceleratorKeysEnabled=false;
                core.Settings.IsGeneralAutofillEnabled=false;core.Settings.IsPasswordAutosaveEnabled=false;
                core.PermissionRequested+=(o,e)=>{e.State=CoreWebView2PermissionState.Deny;};
                core.NewWindowRequested+=(o,e)=>{e.Handled=true;if(e.IsUserInitiated)OpenExternal(e.Uri);};
                core.NavigationStarting+=(o,e)=>{
                    Uri uri;
                    if(Uri.TryCreate(e.Uri,UriKind.Absolute,out uri)&&uri.Scheme=="https"&&uri.Host==Host&&uri.AbsolutePath=="/index.html")return;
                    e.Cancel=true;if(e.IsUserInitiated)OpenExternal(e.Uri);
                };
                core.DownloadStarting+=(o,e)=>{e.Cancel=true;};
                core.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
                core.WebResourceRequested+=(o,e)=>{
                    Uri uri;bool allowed=Uri.TryCreate(e.Request.Uri,UriKind.Absolute,out uri)&&uri.Scheme=="https"&&uri.Host==Host&&resources.Contains(Uri.UnescapeDataString(uri.AbsolutePath));
                    if(!allowed){BlockedRequests++;e.Response=environment.CreateWebResourceResponse(new MemoryStream(new byte[0]),403,"Blocked","Content-Type: text/plain\r\nCache-Control: no-store");}
                };
                core.WebMessageReceived+=(o,e)=>Message(e.Source,e.WebMessageAsJson);
                core.SetVirtualHostNameToFolderMapping(Host,assets,CoreWebView2HostResourceAccessKind.DenyCors);
                core.Navigate("https://"+Host+"/index.html");
            } catch {
                warning.Text="Leitura avançada indisponível. Confira os arquivos da instalação e o Microsoft Edge WebView2 Runtime.";
                warning.BringToFront();initializing=false;
            }
        }
        void Message(string source,string raw) {
            try {
                Uri uri;if(!Uri.TryCreate(source,UriKind.Absolute,out uri)||uri.Scheme!="https"||uri.Host!=Host||uri.AbsolutePath!="/index.html"||raw.Length>4*1024*1024)return;
                Dictionary<string,object> message=json.DeserializeObject(raw) as Dictionary<string,object>;if(message==null)return;
                string type=Value(message,"type");
                if(type=="ready"){ready=true;initializing=false;warning.Visible=false;SendDocument();return;}
                int doc;if(!Int32.TryParse(Value(message,"doc"),out doc)||doc!=documentId)return;
                if(type=="rendered"){LastMetrics=message;return;}
                if(type=="render-error"){warning.Text="A prévia não foi concluída. O texto original está preservado no editor.";return;}
                if(type=="expand-document"){if(ExpandRequested!=null)ExpandRequested();return;}
                if(type=="open-note"&&Value(message,"reference").Length<=2000){if(NoteRequested!=null)NoteRequested(vault,path,Value(message,"reference"),Value(message,"fragment"));return;}
                if(type=="image"&&Value(message,"reference").Length<=2000&&Value(message,"id").Length<120){if(ImageRequested!=null)ImageRequested(doc,Value(message,"id"),vault,path,Value(message,"reference"));return;}
                if(type=="external"){OpenExternal(Value(message,"url"));return;}
                if(type=="copy"){string text=Value(message,"text");if(text.Length<=524288)Clipboard.SetText(text);return;}
                if(type=="export-svg")ExportSvg(Value(message,"value"));
            } catch { /* No note text, URL or exception is written to a log. */ }
        }
        void OpenExternal(string value) {
            Uri uri;if(value.Length>2048||!Uri.TryCreate(value,UriKind.Absolute,out uri)||!(uri.Scheme=="https"||uri.Scheme=="http")||!String.IsNullOrEmpty(uri.UserInfo))return;
            if(MessageBox.Show(this,"Abrir este endereço no navegador?\n\n"+uri.AbsoluteUri,"Link externo",MessageBoxButtons.YesNo,MessageBoxIcon.Question)==DialogResult.Yes)
                try{Process.Start(new ProcessStartInfo(uri.AbsoluteUri){UseShellExecute=true});}catch{}
        }
        void ExportSvg(string text) {
            if(text.Length>4*1024*1024)return;
            XmlReaderSettings settings=new XmlReaderSettings {DtdProcessing=DtdProcessing.Prohibit,XmlResolver=null,MaxCharactersInDocument=4*1024*1024};
            XmlDocument svg=new XmlDocument {XmlResolver=null};
            using(XmlReader reader=XmlReader.Create(new StringReader(text),settings))svg.Load(reader);
            if(svg.DocumentElement.LocalName!="svg"||svg.SelectNodes("//*[local-name()='script' or local-name()='foreignObject' or local-name()='image']").Count>0)return;
            using(SaveFileDialog dialog=new SaveFileDialog {Title="Exportar diagrama",FileName="Animus-diagrama.svg",Filter="Diagrama SVG|*.svg",DefaultExt="svg",AddExtension=true,OverwritePrompt=true})
                if(dialog.ShowDialog(this)==DialogResult.OK&&Path.GetExtension(dialog.FileName).Equals(".svg",StringComparison.OrdinalIgnoreCase))File.WriteAllText(dialog.FileName,svg.OuterXml,new UTF8Encoding(false));
        }
        public void SetDocument(string text,string sourceVault,string sourcePath,string anchor="") {
            markdown=text;vault=sourceVault;path=sourcePath;fragment=anchor;documentId++;LastMetrics.Clear();
            if(ready)SendDocument();else if(Visible&&!initializing)Initialize();
        }
        void SendDocument() {if(ready&&!IsDisposed)web.CoreWebView2.PostWebMessageAsJson(json.Serialize(new Dictionary<string,object>{{"type","render"},{"doc",documentId},{"markdown",markdown},{"fragment",fragment},{"can_expand",ExpandRequested!=null}}));}
        public void Clear(){SetDocument("","","");}
        public void ImageResult(int doc,string id,string dataUrl) {
            if(!ready||doc!=documentId||IsDisposed)return;
            web.CoreWebView2.PostWebMessageAsJson(json.Serialize(new Dictionary<string,object>{{"type","image-result"},{"doc",doc},{"id",id},{"data_url",dataUrl}}));
        }
        public Task<string> InspectAsync(string script) {return web.CoreWebView2.ExecuteScriptAsync(script);}
        protected override void Dispose(bool disposing) {if(disposing)web.Dispose();base.Dispose(disposing);}
    }
}
