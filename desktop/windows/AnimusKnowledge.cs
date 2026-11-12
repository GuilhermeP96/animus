// Canonical Obsidian knowledge UI. No server endpoint or credential is embedded.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace AnimusDesktop {
    static class KnowledgeBridge {
        public static Dictionary<string,object> Run(string data,Dictionary<string,object> request) {
            string python=Path.Combine(data,@"runtime\Scripts\pythonw.exe");
            if(!File.Exists(python))throw new IOException("Runtime indisponível.");
            JavaScriptSerializer json=new JavaScriptSerializer {MaxJsonLength=4*1024*1024};
            ProcessStartInfo info=new ProcessStartInfo(python,"-m animus.desktop_knowledge");
            info.WorkingDirectory=data;info.UseShellExecute=false;info.CreateNoWindow=true;
            info.RedirectStandardInput=true;info.RedirectStandardOutput=true;info.RedirectStandardError=true;
            info.StandardOutputEncoding=Encoding.UTF8;info.StandardErrorEncoding=Encoding.UTF8;
            info.EnvironmentVariables["ANIMUS_DATA_DIR"]=data;
            info.EnvironmentVariables["PYTHONUTF8"]="1";info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
            using(Process p=Process.Start(info)) {
                Task<string> output=p.StandardOutput.ReadToEndAsync();
                Task<string> error=p.StandardError.ReadToEndAsync();
                byte[] input=Encoding.UTF8.GetBytes(json.Serialize(request)+"\n");
                p.StandardInput.BaseStream.Write(input,0,input.Length);p.StandardInput.BaseStream.Flush();p.StandardInput.Close();
                if(!p.WaitForExit(95000)){try{p.Kill();}catch{}throw new IOException("O peer demorou para responder.");}
                Task.WaitAll(output,error);
                if(p.ExitCode!=0 || output.Result.Length>4*1024*1024)throw new IOException("Conhecimento indisponível.");
                Dictionary<string,object> result=json.DeserializeObject(output.Result) as Dictionary<string,object>;
                if(result==null)throw new IOException("Resposta inválida.");
                return result;
            }
        }
    }

    class KnowledgeReaderWindow : BrandedForm {
        static readonly List<KnowledgeReaderWindow> windows=new List<KnowledgeReaderWindow>();
        readonly string data;
        readonly MarkdownPreview preview;
        readonly Label heading;
        bool busy;
        public KnowledgeReaderWindow(string directory,string text,string vault,string path,string title,bool draft) {
            data=directory;BackColor=Brand.Bg;ForeColor=Brand.Text;Font=new Font("Segoe UI",10);
            Text="Animus · "+(String.IsNullOrEmpty(title)?"Leitura Markdown":title);
            Size=new Size(1160,840);MinimumSize=new Size(640,420);StartPosition=FormStartPosition.CenterScreen;
            FormBorderStyle=FormBorderStyle.Sizable;MaximizeBox=true;Icon=Brand.ApplicationIcon();
            preview=new MarkdownPreview(data){Dock=DockStyle.Fill};Controls.Add(preview);
            heading=new Label{Dock=DockStyle.Top,Height=34,Padding=new Padding(12,8,12,4),BackColor=Brand.Surface,ForeColor=Brand.Muted,AutoEllipsis=true};Controls.Add(heading);
            heading.Text=draft?"Somente leitura · prévia do rascunho ainda não salvo":"Somente leitura · "+path;
            KnowledgeWindow.AttachImages(preview,data);
            preview.NoteRequested+=(v,p,reference,anchor)=>{
                if(busy)return;busy=true;heading.Text="Carregando a fonte canônica…";
                Dictionary<string,object> request=new Dictionary<string,object>{{"op","resolve"},{"vault",v},{"path",p},{"reference",reference}};
                Task<Dictionary<string,object>> task=Task.Factory.StartNew(()=>KnowledgeBridge.Run(data,request));
                task.ContinueWith(t=>{
                    if(IsDisposed)return;
                    try{BeginInvoke((MethodInvoker)delegate{
                        busy=false;
                        if(t.IsFaulted){heading.Text="Não foi possível abrir a nota. A leitura atual foi preservada.";return;}
                        Dictionary<string,object> result=t.Result;
                        if(!Object.Equals(result["ok"],true)){heading.Text="Referência indisponível ou ambígua. A leitura atual foi preservada.";return;}
                        Dictionary<string,object> note=result["data"] as Dictionary<string,object>;
                        string nextPath=Convert.ToString(note["path"]);Text="Animus · "+Convert.ToString(note["title"]);heading.Text="Somente leitura · "+nextPath;
                        preview.SetDocument(Convert.ToString(note["body"]),Convert.ToString(note["vault"]),nextPath,anchor);
                    });}catch(InvalidOperationException){}
                });
            };
            preview.SetDocument(text,vault,path);windows.Add(this);FormClosed+=(o,e)=>windows.Remove(this);
        }
        public static void CloseAll(){foreach(KnowledgeReaderWindow window in windows.ToArray())window.Dispose();windows.Clear();}
    }

    class DarkButton : Button {
        bool hover,pressed;
        public bool SelectedStyle;
        public DarkButton() {
            FlatStyle=FlatStyle.Flat;FlatAppearance.BorderSize=0;UseVisualStyleBackColor=false;
            SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer,true);
        }
        protected override void OnMouseEnter(EventArgs e){hover=true;Invalidate();base.OnMouseEnter(e);}
        protected override void OnMouseLeave(EventArgs e){hover=false;pressed=false;Invalidate();base.OnMouseLeave(e);}
        protected override void OnMouseDown(MouseEventArgs e){pressed=true;Invalidate();base.OnMouseDown(e);}
        protected override void OnMouseUp(MouseEventArgs e){pressed=false;Invalidate();base.OnMouseUp(e);}
        protected override void OnEnabledChanged(EventArgs e){Invalidate();base.OnEnabledChanged(e);}
        protected override void OnPaint(PaintEventArgs e) {
            Color background=!Enabled?Color.FromArgb(14,21,29):pressed?Color.FromArgb(24,54,69):SelectedStyle?Color.FromArgb(20,59,76):hover?Color.FromArgb(23,43,57):Brand.Surface;
            Color foreground=Enabled?Brand.Text:Color.FromArgb(116,137,158);
            using(SolidBrush brush=new SolidBrush(background))e.Graphics.FillRectangle(brush,ClientRectangle);
            using(Pen pen=new Pen((Focused&&Enabled)||SelectedStyle?Brand.Cyan:Brand.Border))e.Graphics.DrawRectangle(pen,0,0,Width-1,Height-1);
            TextRenderer.DrawText(e.Graphics,Text,Font,ClientRectangle,foreground,TextFormatFlags.HorizontalCenter|TextFormatFlags.VerticalCenter|TextFormatFlags.EndEllipsis);
            if(Focused&&ShowFocusCues)ControlPaint.DrawFocusRectangle(e.Graphics,new Rectangle(4,4,Width-8,Height-8),foreground,background);
        }
    }

    class DarkComboBox : ComboBox {
        [DllImport("uxtheme.dll",CharSet=CharSet.Unicode)] static extern int SetWindowTheme(IntPtr handle,string application,string idList);
        public DarkComboBox() {
            DrawMode=DrawMode.OwnerDrawFixed;FlatStyle=FlatStyle.Flat;ItemHeight=20;
            BackColor=Brand.Surface;ForeColor=Brand.Text;
        }
        protected override void OnHandleCreated(EventArgs e){base.OnHandleCreated(e);try{SetWindowTheme(Handle,"","");}catch(DllNotFoundException){}}
        protected override void OnDrawItem(DrawItemEventArgs e) {
            if(e.Index<0)return;
            bool selected=(e.State&DrawItemState.Selected)==DrawItemState.Selected;
            Color background=selected?Color.FromArgb(20,73,96):Brand.Surface;
            using(SolidBrush brush=new SolidBrush(background))e.Graphics.FillRectangle(brush,e.Bounds);
            TextRenderer.DrawText(e.Graphics,GetItemText(Items[e.Index]),Font,e.Bounds,Brand.Text,
                TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.EndEllipsis);
            if((e.State&DrawItemState.Focus)==DrawItemState.Focus)e.DrawFocusRectangle();
        }
    }

    class DarkTabControl : UserControl {
        readonly TableLayoutPanel header=new TableLayoutPanel();
        readonly Panel content=new Panel();
        readonly List<Control> pages=new List<Control>();
        readonly List<DarkButton> buttons=new List<DarkButton>();
        int selected=-1;
        public event EventHandler SelectedIndexChanged;
        public DarkTabControl() {
            BackColor=Brand.Bg;ForeColor=Brand.Text;
            content.Dock=DockStyle.Fill;content.BackColor=Brand.Surface;content.Padding=new Padding(2);
            header.Dock=DockStyle.Top;header.Height=36;header.BackColor=Brand.Bg;header.ColumnCount=3;header.RowCount=1;
            header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,33.333f));header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,33.333f));header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,33.334f));
            Controls.Add(content);Controls.Add(header);
        }
        public void AddPage(string title,Control page) {
            int index=pages.Count;page.Dock=DockStyle.Fill;page.BackColor=Brand.Surface;page.Visible=false;content.Controls.Add(page);pages.Add(page);
            DarkButton button=new DarkButton {Text=title,Dock=DockStyle.Fill,Margin=new Padding(index==0?0:4,0,0,4),AccessibleName=title,AccessibleRole=AccessibleRole.PageTab};
            button.Click+=(o,e)=>SelectedIndex=index;buttons.Add(button);header.Controls.Add(button,index,0);
            if(selected<0)SelectedIndex=0;
        }
        public int SelectedIndex {
            get{return selected;}
            set{
                if(value<0||value>=pages.Count||value==selected)return;
                selected=value;
                for(int i=0;i<pages.Count;i++){pages[i].Visible=i==selected;buttons[i].SelectedStyle=i==selected;buttons[i].Invalidate();}
                pages[selected].BringToFront();if(SelectedIndexChanged!=null)SelectedIndexChanged(this,EventArgs.Empty);
            }
        }
    }

    class KnowledgeWindow : BrandedForm {
        readonly string data;
        ComboBox vault,statusFilter,state,sensitivity;
        TextBox query,title,project,body;
        MarkdownPreview preview,graphPreview;
        static readonly SemaphoreSlim imagePool=new SemaphoreSlim(2);
        TreeView notes;
        DarkTabControl tabs;
        Label count,origin,feedback,sync;
        Button save;
        readonly List<Control> actions=new List<Control>();
        Dictionary<string,object> current;
        bool dirty,busy,loading,isNew;
        string lastVault="";
        string graphDocument="";
        System.Windows.Forms.Timer poll=new System.Windows.Forms.Timer();
        Font previewCode=new Font("Consolas",10);
        public bool HasUnsaved {get{return dirty;}}

        static string Get(Dictionary<string,object> item,string key,string fallback="") {
            object value;return item!=null&&item.TryGetValue(key,out value)&&value!=null?Convert.ToString(value):fallback;
        }
        static bool Flag(Dictionary<string,object> item,string key) {return Get(item,key)=="True";}
        static Dictionary<string,object> Request(string op) {return new Dictionary<string,object>{{"op",op}};}
        Dictionary<string,object> VaultRequest(string op) {
            Dictionary<string,object> r=Request(op);r["vault"]=Convert.ToString(vault.SelectedItem);return r;
        }
        Label LabelAt(string text,int x,int y,int width,int height,Color color,float size) {
            Label l=new Label {Text=text,Left=x,Top=y,Width=width,Height=height,ForeColor=color,
                BackColor=Color.Transparent,Font=new Font("Segoe UI",size),AccessibleName=text};Controls.Add(l);return l;
        }
        Button ButtonAt(string text,int x,int y,int width,EventHandler handler) {
            Button b=new DarkButton {Text=text,Left=x,Top=y,Width=width,Height=34,
                BackColor=Brand.Surface,ForeColor=Brand.Cyan,AccessibleName=text};
            b.Click+=handler;Controls.Add(b);actions.Add(b);return b;
        }
        TextBox TextAt(string name,int x,int y,int width) {
            TextBox t=new TextBox {Left=x,Top=y,Width=width,BackColor=Brand.Surface,ForeColor=Brand.Text,
                BorderStyle=BorderStyle.FixedSingle,AccessibleName=name};Controls.Add(t);return t;
        }
        ComboBox Choice(string name,int x,int y,int width,string[] choices) {
            ComboBox c=new DarkComboBox {Left=x,Top=y,Width=width,DropDownStyle=ComboBoxStyle.DropDownList,
                BackColor=Brand.Surface,ForeColor=Brand.Text,AccessibleName=name};c.Items.AddRange(choices);
            if(c.Items.Count>0)c.SelectedIndex=0;Controls.Add(c);return c;
        }
        public KnowledgeWindow(string directory) {
            data=directory;Text="Animus · Conhecimento Obsidian";BackColor=Brand.Bg;ForeColor=Brand.Text;
            Font=new Font("Segoe UI",10);ClientSize=new Size(1180,800);MinimumSize=new Size(960,640);
            AutoScroll=true;AutoScrollMinSize=new Size(1180,800);KeyPreview=true;
            MaximizeBox=true;FormBorderStyle=FormBorderStyle.Sizable;SizeGripStyle=SizeGripStyle.Show;
            StartPosition=FormStartPosition.CenterScreen;Icon=Brand.ApplicationIcon();
            LabelAt("A N I M U S  /  CONHECIMENTO",24,20,850,34,Brand.Text,21);
            LabelAt("O mesmo vault. Sua curadoria, conectada ao Animus.",26,60,1050,24,Brand.Muted,10);
            LabelAt("VAULT",26,99,150,18,Brand.Gold,8);
            vault=Choice("Vault canônico",26,120,220,new string[0]);
            LabelAt("BUSCAR NO TEXTO OU PROJETO",260,99,380,18,Brand.Gold,8);
            query=TextAt("Buscar notas",260,120,420);query.MaxLength=200;
            query.KeyDown+=(o,e)=>{if(e.KeyCode==Keys.Enter&&!busy){e.SuppressKeyPress=true;Search(true);}};
            statusFilter=Choice("Filtrar status",694,120,140,new string[]{"Todos","candidato","curado","verificado","depreciado"});
            ButtonAt("Buscar",848,116,112,(o,e)=>Search(true));
            ButtonAt("Atualizar índice",972,116,180,(o,e)=>RefreshIndex());
            notes=new TreeView {Left=26,Top=171,Width=370,Height=515,HideSelection=false,
                BackColor=Brand.Surface,ForeColor=Brand.Text,LineColor=Brand.Border,ShowLines=true,
                ShowPlusMinus=true,ShowRootLines=true,ShowNodeToolTips=true,ItemHeight=24,
                BorderStyle=BorderStyle.FixedSingle,AccessibleName="Hierarquia de notas do vault"};
            Controls.Add(notes);
            notes.AfterSelect+=(o,e)=>{if(!busy&&!loading&&e.Node!=null&&e.Node.Tag is Dictionary<string,object>)OpenSelected();};
            count=LabelAt("Escolha um vault para começar.",26,695,370,25,Brand.Muted,9);
            ButtonAt("Expandir tudo",26,730,116,(o,e)=>notes.ExpandAll());
            ButtonAt("Recolher",150,730,100,(o,e)=>notes.CollapseAll());
            ButtonAt("Nova nota",258,730,138,(o,e)=>NewNote());
            LabelAt("TÍTULO",420,170,320,18,Brand.Gold,8);title=TextAt("Título da nota",420,191,732);title.MaxLength=180;
            LabelAt("PROJETO",420,228,300,18,Brand.Gold,8);project=TextAt("Projeto",420,249,330);project.MaxLength=180;
            LabelAt("STATUS",766,228,180,18,Brand.Gold,8);state=Choice("Status de curadoria",766,249,184,new string[]{"candidato","curado","verificado","depreciado"});
            LabelAt("SENSIBILIDADE",966,228,190,18,Brand.Gold,8);sensitivity=Choice("Sensibilidade",966,249,186,new string[]{"publico","interno","restrito"});sensitivity.SelectedIndex=1;
            origin=LabelAt("Fonte: selecione uma nota.",420,287,732,32,Brand.Muted,9);
            tabs=new DarkTabControl {Left=420,Top=329,Width=732,Height=357,AccessibleName="Texto, leitura e grafo do vault"};
            Panel edit=new Panel {BackColor=Brand.Surface};
            Panel read=new Panel {BackColor=Brand.Surface};
            Panel graph=new Panel {BackColor=Brand.Surface};
            tabs.AddPage("Editar Markdown",edit);tabs.AddPage("Leitura",read);tabs.AddPage("Grafo do vault",graph);Controls.Add(tabs);
            body=new TextBox {Dock=DockStyle.Fill,Multiline=true,AcceptsReturn=true,AcceptsTab=true,ScrollBars=ScrollBars.Both,
                WordWrap=false,MaxLength=512*1024,BackColor=Brand.Surface,ForeColor=Brand.Text,BorderStyle=BorderStyle.None,
                Font=previewCode,AccessibleName="Texto Markdown da nota"};edit.Controls.Add(body);
            preview=new MarkdownPreview(data) {Dock=DockStyle.Fill};read.Controls.Add(preview);
            AttachPreview(preview,true);
            preview.ExpandRequested+=OpenReader;
            graphPreview=new MarkdownPreview(data) {Dock=DockStyle.Fill};graph.Controls.Add(graphPreview);
            graphPreview.ExpandRequested+=OpenGraphReader;
            tabs.SelectedIndexChanged+=(o,e)=>{if(tabs.SelectedIndex==1)RenderPreview();else if(tabs.SelectedIndex==2)RenderGraphPreview();};
            tabs.SelectedIndex=1;
            save=ButtonAt("Salvar no vault",420,730,170,(o,e)=>SaveNote());
            ButtonAt("Recarregar nota",602,730,170,(o,e)=>ReloadNote());
            ButtonAt("Sincronizar",784,730,150,(o,e)=>SyncNow());
            Button reader=ButtonAt("Abrir só leitura ↗",946,730,206,(o,e)=>OpenReader());
            sync=LabelAt("",420,695,732,24,Brand.Muted,9);
            feedback=LabelAt("",420,772,732,22,Brand.Muted,9);
            title.TextChanged+=Changed;project.TextChanged+=Changed;body.TextChanged+=Changed;
            state.SelectedIndexChanged+=Changed;sensitivity.SelectedIndexChanged+=Changed;
            vault.SelectedIndexChanged+=(o,e)=>{
                if(loading||busy)return;
                if(!ConfirmDiscard()){loading=true;vault.SelectedItem=lastVault;loading=false;return;}
                lastVault=Convert.ToString(vault.SelectedItem);ClearEditor();Search(true);
            };
            FormClosing+=(o,e)=>{if(!ConfirmDiscard())e.Cancel=true;};
            KeyDown+=(o,e)=>{
                if(busy)return;
                if(e.Control&&e.Shift&&e.KeyCode==Keys.R){e.SuppressKeyPress=true;OpenReader();}
                else if(e.Control&&e.KeyCode==Keys.S){e.SuppressKeyPress=true;SaveNote();}
                else if(e.Control&&e.KeyCode==Keys.F){e.SuppressKeyPress=true;query.Focus();}
                else if(e.Control&&e.KeyCode==Keys.N){e.SuppressKeyPress=true;NewNote();}
                else if(e.KeyCode==Keys.F5){e.SuppressKeyPress=true;Search(false);}
            };
            Shown+=(o,e)=>LoadVaults();
            poll.Interval=7000;poll.Tick+=(o,e)=>{if(!busy&&current!=null&&!isNew)PollState();};poll.Start();
            SetEditable(false);
            // A scrollable minimum canvas keeps controls usable on small screens;
            // anchors inside it grow the reading/editor area on larger windows.
            Panel canvas=new Panel {Size=new Size(1180,800),BackColor=Brand.Bg};
            Control[] controls=new Control[Controls.Count];Controls.CopyTo(controls,0);
            foreach(Control c in controls){
                if(c.Left>=420&&c.Width>=700)c.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;
                if(c.Left>=694&&c.Top<150)c.Anchor=AnchorStyles.Top|AnchorStyles.Right;
                if(c.Left>=766&&(c.Top==228||c.Top==249))c.Anchor=AnchorStyles.Top|AnchorStyles.Right;
                if(c.Top>=695)c.Anchor=AnchorStyles.Bottom|AnchorStyles.Left|(c.Width>=700?AnchorStyles.Right:AnchorStyles.None);
            }
            query.Anchor=project.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;
            notes.Anchor=AnchorStyles.Top|AnchorStyles.Bottom|AnchorStyles.Left;
            tabs.Anchor=AnchorStyles.Top|AnchorStyles.Bottom|AnchorStyles.Left|AnchorStyles.Right;
            reader.Anchor=AnchorStyles.Bottom|AnchorStyles.Right;
            Controls.Clear();canvas.Controls.AddRange(controls);Controls.Add(canvas);
            ClientSizeChanged+=(o,e)=>canvas.Size=new Size(Math.Max(1180,ClientSize.Width),Math.Max(800,ClientSize.Height));
            canvas.Size=new Size(Math.Max(1180,ClientSize.Width),Math.Max(800,ClientSize.Height));
        }
        void OpenReader(){
            if(body.TextLength==0){feedback.Text="Selecione uma nota para abrir a leitura.";return;}
            new KnowledgeReaderWindow(data,body.Text,current==null?Convert.ToString(vault.SelectedItem):Get(current,"vault"),
                current==null?"":Get(current,"path"),title.Text,dirty||isNew).Show();
        }
        void OpenGraphReader(){
            if(String.IsNullOrEmpty(graphDocument)){feedback.Text="Busque notas para montar o grafo do vault.";return;}
            new KnowledgeReaderWindow(data,graphDocument,Convert.ToString(vault.SelectedItem),"","Grafo do vault",false).Show();
        }
        void AttachPreview(MarkdownPreview target,bool editor) {
            target.NoteRequested+=(v,p,reference,anchor)=>{
                if(busy||(editor&&!ConfirmDiscard()))return;
                Dictionary<string,object> r=Request("resolve");r["vault"]=v;r["path"]=p;r["reference"]=reference;
                Call(r,note=>{if(editor)LoadNote(note);target.SetDocument(Get(note,"body"),Get(note,"vault"),Get(note,"path"),anchor);});
            };
            AttachImages(target,data);
        }
        public static void AttachImages(MarkdownPreview target,string directory) {
            target.ImageRequested+=(doc,id,v,p,reference)=>{
                Task.Factory.StartNew(()=>{
                    imagePool.Wait();string url="";
                    try{if(!target.IsDisposed){Dictionary<string,object> r=Request("attachment");r["vault"]=v;r["path"]=p;r["reference"]=reference;Dictionary<string,object> result=KnowledgeBridge.Run(directory,r);if(Flag(result,"ok"))url=Get(result["data"] as Dictionary<string,object>,"data_url");}}catch{}finally{imagePool.Release();}
                    if(!target.IsDisposed)try{target.BeginInvoke((MethodInvoker)delegate {if(!target.IsDisposed)target.ImageResult(doc,id,url);});}catch(InvalidOperationException){}
                });
            };
        }
        void Changed(object o,EventArgs e) {if(!loading){dirty=true;sync.Text="Alterações ainda não salvas.";}}
        bool ConfirmDiscard() {
            if(busy){feedback.Text="Aguarde a operação em andamento antes de fechar ou trocar de nota.";return false;}
            return !dirty||MessageBox.Show(this,"Descartar as alterações ainda não salvas?","Animus",MessageBoxButtons.YesNo,MessageBoxIcon.Question)==DialogResult.Yes;
        }
        public bool ConfirmExit() {return ConfirmDiscard();}
        void SetEditable(bool enabled) {title.ReadOnly=project.ReadOnly=body.ReadOnly=!enabled;state.Enabled=sensitivity.Enabled=enabled;save.Enabled=enabled&&!busy;}
        void ClearEditor() {
            loading=true;current=null;isNew=false;title.Clear();project.Clear();body.Clear();preview.Clear();
            loading=false;dirty=false;SetEditable(false);sync.Text="";origin.Text="Fonte: selecione uma nota.";
        }
        void RestoreControls() {
            foreach(Control c in actions)c.Enabled=true;
            vault.Enabled=query.Enabled=statusFilter.Enabled=notes.Enabled=true;
            SetEditable(isNew||Flag(current,"editable"));if(isNew)state.Enabled=sensitivity.Enabled=false;
        }
        void Call(Dictionary<string,object> request,Action<Dictionary<string,object>> success) {
            if(busy)return;busy=true;foreach(Control c in actions)c.Enabled=false;feedback.Text="Aguarde…";
            vault.Enabled=query.Enabled=statusFilter.Enabled=notes.Enabled=false;SetEditable(false);
            Task<Dictionary<string,object>> task=Task.Factory.StartNew(()=>KnowledgeBridge.Run(data,request));
            task.ContinueWith(t=>{
                if(IsDisposed)return;
                try {BeginInvoke((MethodInvoker)delegate {
                    busy=false;RestoreControls();
                    if(t.IsFaulted){feedback.Text="Não foi possível acessar o conhecimento. Confira o runtime e tente novamente.";return;}
                    Dictionary<string,object> result=t.Result;
                    if(!Flag(result,"ok")){feedback.Text=Get(result,"message","Operação não concluída.");return;}
                    feedback.Text="";
                    Dictionary<string,object> value=result["data"] as Dictionary<string,object>;
                    success(value);
                });}catch(InvalidOperationException){}
            });
        }
        void LoadVaults() {
            Call(Request("status"),r=>{
                loading=true;vault.Items.Clear();IEnumerable rows=r["vaults"] as IEnumerable;
                if(rows!=null)foreach(object x in rows){Dictionary<string,object> v=x as Dictionary<string,object>;if(v!=null&&Flag(v,"available"))vault.Items.Add(Get(v,"name"));}
                if(vault.Items.Count>0)vault.SelectedIndex=0;lastVault=Convert.ToString(vault.SelectedItem);loading=false;
                if(vault.Items.Count==0){feedback.Text="Nenhum vault disponível no peer. Configure o vault canônico antes de usar esta área.";return;}
                Search(true);
            });
        }
        TreeNode Folder(TreeNodeCollection nodes,string label,string key) {
            string name="folder:"+key;
            if(nodes.ContainsKey(name))return nodes[name];
            TreeNode folder=new TreeNode(label){Name=name,ForeColor=Brand.Cyan,ToolTipText=key};nodes.Add(folder);return folder;
        }
        void AddTreeNote(Dictionary<string,object> note) {
            string path=Get(note,"path").Replace('\\','/');string[] parts=path.Split(new[]{'/'},StringSplitOptions.RemoveEmptyEntries);
            TreeNodeCollection level=notes.Nodes;string prefix="";
            if(parts.Length==1){TreeNode root=Folder(level,"Raiz","/");level=root.Nodes;}
            else for(int i=0;i<parts.Length-1;i++){
                prefix+=(prefix.Length==0?"":"/")+parts[i];TreeNode folder=Folder(level,parts[i],prefix);level=folder.Nodes;
            }
            string status=Get(note,"status","candidato");
            TreeNode leaf=new TreeNode(Get(note,"title")+"  ·  "+status){Name="note:"+path,Tag=note,ToolTipText=path,
                ForeColor=status=="verificado"?Color.FromArgb(92,224,177):status=="curado"?Color.FromArgb(119,190,255):status=="depreciado"?Color.FromArgb(143,151,160):Brand.Text};
            level.Add(leaf);
        }
        TreeNode FindNote(TreeNodeCollection nodes,string path) {
            string key="note:"+path;
            foreach(TreeNode node in nodes){if(node.Name==key)return node;TreeNode found=FindNote(node.Nodes,path);if(found!=null)return found;}
            return null;
        }
        void RestoreTreeSelection(string path) {
            if(String.IsNullOrEmpty(path)){foreach(TreeNode node in notes.Nodes)node.Collapse();return;}
            TreeNode selected=FindNote(notes.Nodes,path);if(selected==null)return;
            selected.EnsureVisible();notes.SelectedNode=selected;
        }
        static string NormalizeGraphKey(string value) {
            if(String.IsNullOrEmpty(value))return "";
            try{value=Uri.UnescapeDataString(value);}catch(UriFormatException){}
            value=value.Split('#')[0].Replace('\\','/').Trim();
            if(value.EndsWith(".md",StringComparison.OrdinalIgnoreCase))value=value.Substring(0,value.Length-3);
            List<string> parts=new List<string>();
            foreach(string raw in value.Split(new[]{'/'},StringSplitOptions.RemoveEmptyEntries)){
                if(raw==".")continue;if(raw==".."){if(parts.Count>0)parts.RemoveAt(parts.Count-1);continue;}parts.Add(raw);
            }
            return String.Join("/",parts.ToArray()).ToLowerInvariant();
        }
        static void RegisterAlias(Dictionary<string,int> aliases,string alias,int index) {
            alias=NormalizeGraphKey(alias);if(alias.Length==0)return;
            int existing;if(aliases.TryGetValue(alias,out existing)&&existing!=index)aliases[alias]=-1;else if(!aliases.ContainsKey(alias))aliases[alias]=index;
        }
        static int ResolveGraphLink(Dictionary<string,int> aliases,string current,string reference) {
            string path=NormalizeGraphKey(current),link=NormalizeGraphKey(reference),parent="";int slash=path.LastIndexOf('/');if(slash>=0)parent=path.Substring(0,slash);
            string[] candidates={NormalizeGraphKey((parent.Length==0?"":parent+"/")+link),link,link.Contains("/")?link:NormalizeGraphKey(link)};
            foreach(string candidate in candidates){int value;if(candidate.Length>0&&aliases.TryGetValue(candidate,out value)&&value>=0)return value;}
            return -1;
        }
        static string MermaidLabel(string value) {
            value=(value??"").Replace("\\","/").Replace("\"","'").Replace("[","(").Replace("]",")").Replace("\r"," ").Replace("\n"," ");
            return value.Length>64?value.Substring(0,61)+"...":value;
        }
        void RenderGraph(List<Dictionary<string,object>> rows) {
            StringBuilder markdown=new StringBuilder();markdown.AppendLine("# Grafo do vault").AppendLine();
            if(rows.Count==0){markdown.AppendLine("Nenhuma nota corresponde aos filtros atuais.");graphDocument=markdown.ToString();RenderGraphPreview();return;}
            Dictionary<string,int> aliases=new Dictionary<string,int>(StringComparer.OrdinalIgnoreCase);
            for(int i=0;i<rows.Count;i++){
                string path=Get(rows[i],"path"),stem=Path.GetFileNameWithoutExtension(path.Replace('/','\\'));
                RegisterAlias(aliases,path,i);RegisterAlias(aliases,stem,i);RegisterAlias(aliases,Get(rows[i],"title"),i);
            }
            List<Tuple<int,int>> edges=new List<Tuple<int,int>>();HashSet<string> seenEdges=new HashSet<string>();HashSet<int> included=new HashSet<int>();
            for(int source=0;source<rows.Count&&edges.Count<240;source++){
                object rawLinks;if(!rows[source].TryGetValue("links",out rawLinks))continue;IEnumerable links=rawLinks as IEnumerable;if(links==null)continue;
                foreach(object raw in links){
                    int target=ResolveGraphLink(aliases,Get(rows[source],"path"),Convert.ToString(raw));if(target<0||target==source)continue;
                    int additional=(included.Contains(source)?0:1)+(included.Contains(target)?0:1);if(included.Count+additional>120)continue;
                    string edge=source+">"+target;if(!seenEdges.Add(edge))continue;
                    included.Add(source);included.Add(target);edges.Add(Tuple.Create(source,target));if(edges.Count>=240)break;
                }
            }
            for(int i=0;i<rows.Count&&included.Count<Math.Min(40,rows.Count)&&included.Count<120;i++)included.Add(i);
            List<int> order=new List<int>(included);order.Sort();Dictionary<int,int> ids=new Dictionary<int,int>();
            markdown.AppendLine("Visão derivada dos wikilinks canônicos. Use a busca para reduzir o recorte quando o vault for grande.").AppendLine();
            markdown.AppendLine("```mermaid").AppendLine("flowchart LR");
            for(int i=0;i<order.Count;i++){int source=order[i];ids[source]=i;markdown.Append("n").Append(i).Append("[\"").Append(MermaidLabel(Get(rows[source],"title"))).AppendLine("\"]");}
            foreach(Tuple<int,int> edge in edges)if(ids.ContainsKey(edge.Item1)&&ids.ContainsKey(edge.Item2))markdown.Append("n").Append(ids[edge.Item1]).Append(" --> n").Append(ids[edge.Item2]).AppendLine();
            markdown.AppendLine("classDef candidato fill:#2b2414,stroke:#c8a84e,color:#e8f0f8");
            markdown.AppendLine("classDef curado fill:#102d45,stroke:#77beff,color:#e8f0f8");
            markdown.AppendLine("classDef verificado fill:#103c31,stroke:#5ce0b1,color:#e8f0f8");
            markdown.AppendLine("classDef depreciado fill:#202830,stroke:#8f97a0,color:#b9c5d1");
            for(int i=0;i<order.Count;i++){string status=Get(rows[order[i]],"status","candidato");if(status!="curado"&&status!="verificado"&&status!="depreciado")status="candidato";markdown.Append("class n").Append(i).Append(' ').Append(status).AppendLine();}
            markdown.AppendLine("```").AppendLine().Append("Exibindo ").Append(order.Count).Append(" de ").Append(rows.Count).Append(" notas e ").Append(edges.Count).AppendLine(" vínculos no recorte atual.");
            graphDocument=markdown.ToString();RenderGraphPreview();
        }
        void RenderGraphPreview(){graphPreview.SetDocument(graphDocument,Convert.ToString(vault.SelectedItem),"");}
        void Search(bool reset) {
            if(vault.SelectedItem==null)return;
            Dictionary<string,object> r=VaultRequest("list");r["query"]=query.Text;r["status"]=statusFilter.SelectedIndex==0?"":Convert.ToString(statusFilter.SelectedItem);r["offset"]=0;r["limit"]=2000;
            Call(r,result=>{
                loading=true;string selected=current==null?"":Get(current,"path");List<Dictionary<string,object>> visible=new List<Dictionary<string,object>>();
                notes.BeginUpdate();
                try{
                    notes.Nodes.Clear();IEnumerable rows=result["notes"] as IEnumerable;
                    if(rows!=null)foreach(object item in rows) {
                        Dictionary<string,object> note=item as Dictionary<string,object>;if(note==null)continue;
                        visible.Add(note);AddTreeNote(note);
                    }
                }finally{notes.EndUpdate();}
                RestoreTreeSelection(selected);
                count.Text=Get(result,"total")+" notas"+(Flag(result,"has_more")?" · "+visible.Count+" carregadas":"")+(Flag(result,"truncated")?" · varredura limitada":"");
                try{RenderGraph(visible);}catch(Exception){graphDocument="# Grafo do vault\n\nNão foi possível montar esta visualização. Refine a busca e tente novamente.";RenderGraphPreview();feedback.Text="A árvore foi carregada, mas o grafo deste recorte não pôde ser montado.";}
                loading=false;
            });
        }
        void OpenSelected() {
            if(!ConfirmDiscard())return;
            Dictionary<string,object> note=notes.SelectedNode==null?null:notes.SelectedNode.Tag as Dictionary<string,object>;if(note==null)return;
            Dictionary<string,object> r=Request("read");r["vault"]=Get(note,"vault");r["path"]=Get(note,"path");Call(r,LoadNote);
        }
        void LoadNote(Dictionary<string,object> note) {
            current=note;isNew=false;loading=true;title.Text=Get(note,"title");project.Text=Get(note,"projeto");
            body.Text=Get(note,"body");state.SelectedItem=Get(note,"status","candidato");sensitivity.SelectedItem=Get(note,"sensibilidade","interno");
            origin.Text="Fonte canônica: "+Get(note,"vault")+" / "+Get(note,"path");
            loading=false;dirty=false;SetEditable(Flag(note,"editable"));UpdateSync(note);RenderPreview();
            feedback.Text=Get(note,"warning");
        }
        void UpdateSync(Dictionary<string,object> note) {
            string value=Get(note,"sync_state");sync.Text=value=="synced"?"● Sincronizada com o hub":value=="pending"?"● Salva no vault · aguardando envio":"● Arquivo canônico · atualização do índice pendente";
            sync.ForeColor=value=="synced"?Color.FromArgb(0,235,151):Brand.Gold;
        }
        void NewNote() {
            if(vault.SelectedItem==null||!ConfirmDiscard())return;
            current=null;isNew=true;loading=true;title.Text="";project.Text="";body.Text="";state.SelectedIndex=0;sensitivity.SelectedIndex=1;
            origin.Text="Nova nota no vault "+Convert.ToString(vault.SelectedItem)+" · pasta Conhecimento";
            loading=false;dirty=false;SetEditable(true);state.Enabled=sensitivity.Enabled=false;
            sync.Text="A nota será criada no vault existente, indexada e colocada na fila de sincronização.";title.Focus();
        }
        void SaveNote() {
            if(isNew) {
                Dictionary<string,object> create=VaultRequest("create");create["title"]=title.Text;create["projeto"]=project.Text;create["body"]=body.Text;
                Call(create,created=>{LoadNote(created["note"] as Dictionary<string,object>);Search(false);});return;
            }
            if(current==null||!Flag(current,"editable"))return;
            Dictionary<string,object> patch=new Dictionary<string,object>();
            string[] keys={"title","projeto","status","sensibilidade"};string[] values={title.Text,project.Text,Convert.ToString(state.SelectedItem),Convert.ToString(sensitivity.SelectedItem)};
            for(int i=0;i<keys.Length;i++)if(values[i]!=Get(current,keys[i]))patch[keys[i]]=values[i];
            bool acknowledge=false;
            if(Convert.ToString(state.SelectedItem)=="verificado"&&(Get(current,"status")!="verificado"||body.Text!=Get(current,"body"))) {
                acknowledge=MessageBox.Show(this,"Você conferiu o conteúdo desta nota com a fonte e confirma o status verificado?","Verificar conhecimento",MessageBoxButtons.YesNo,MessageBoxIcon.Question)==DialogResult.Yes;
                if(!acknowledge)return;
            }
            Dictionary<string,object> r=Request("save");r["vault"]=Get(current,"vault");r["path"]=Get(current,"path");r["etag"]=Get(current,"etag");
            r["body"]=body.Text;r["patch"]=patch;r["verified_ack"]=acknowledge;
            Call(r,result=>{LoadNote(result["note"] as Dictionary<string,object>);Search(false);});
        }
        void ReloadNote() {
            if(current==null||!ConfirmDiscard())return;
            Dictionary<string,object> r=Request("read");r["vault"]=Get(current,"vault");r["path"]=Get(current,"path");Call(r,LoadNote);
        }
        void RefreshIndex() {
            if(vault.SelectedItem==null)return;
            Call(VaultRequest("refresh"),r=>{feedback.Text=Get(r,"indexed")+" notas indexadas no mesmo peer.";Search(false);});
        }
        void SyncNow() {Call(Request("sync"),r=>{feedback.Text=Get(r,"sent")+" registros enviados · "+Get(r,"pending_notes")+" notas na fila.";});}
        void PollState() {
            Dictionary<string,object> r=Request("read");r["vault"]=Get(current,"vault");r["path"]=Get(current,"path");
            Call(r,note=>{
                if(!dirty)UpdateSync(note);
                if(Get(note,"etag")!=Get(current,"etag")){sync.Text="A fonte mudou. Recarregue para ver a versão atual; seu texto foi mantido.";sync.ForeColor=Brand.Gold;}
            });
        }
        void RenderPreview() {
            preview.SetDocument(body.Text,current==null?Convert.ToString(vault.SelectedItem):Get(current,"vault"),current==null?"":Get(current,"path"));
        }
        protected override void Dispose(bool disposing) {
            if(disposing){poll.Stop();poll.Dispose();previewCode.Dispose();if(graphPreview!=null)graphPreview.Dispose();}
            base.Dispose(disposing);
        }
    }
}
