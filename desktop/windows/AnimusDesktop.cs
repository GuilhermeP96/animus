// Animus desktop. AGPL-3.0-only; Copyright Guilherme Pinheiro / Datano.
// No endpoint, credential, configuration or memory is compiled into this app.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Animus")]
[assembly: System.Reflection.AssemblyProduct("Animus Peer Desktop")]
[assembly: System.Reflection.AssemblyCompany("Guilherme Pinheiro / Datano")]
[assembly: System.Reflection.AssemblyVersion("0.9.2.0")]

namespace AnimusDesktop {
    static class Program {
        [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
        [DllImport("shell32.dll", CharSet=CharSet.Unicode)] static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
        [STAThread] static void Main(string[] args) {
            SetProcessDPIAware();
            SetCurrentProcessExplicitAppUserModelID("Datano.Animus.Peer");
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string data = Environment.GetEnvironmentVariable("ANIMUS_DATA_DIR");
            if (String.IsNullOrEmpty(data)) data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".animus");
            bool background = false, quit = false;
            string capture = null;
            for (int i=0; i<args.Length; i++) {
                if (args[i]=="--data-dir" && i+1<args.Length) data=args[++i];
                else if (args[i]=="--background") background=true;
                else if (args[i]=="--quit") quit=true;
                else if (args[i]=="--capture" && i+1<args.Length) capture=args[++i];
                else if (args[i]=="--export-icon" && i+1<args.Length) {
                    File.WriteAllBytes(args[++i],Brand.IconFile());
                    return;
                }
                else if (args[i]=="--export-preview" && i+1<args.Length) {
                    Brand.Preview(args[++i]);
                    return;
                }
            }
            data=Path.GetFullPath(data);
            if (data.StartsWith(@"\\")) return; // Local IPC only.
            string token;
            using (SHA256 hash=SHA256.Create()) token=BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(data.ToUpperInvariant()))).Replace("-", "").Substring(0,20);
            token=System.Security.Principal.WindowsIdentity.GetCurrent().User.Value+"-"+token;
            bool created;
            using (Mutex mutex=new Mutex(true,@"Local\AnimusDesktop-"+token,out created))
            using (EventWaitHandle show=new EventWaitHandle(false,EventResetMode.AutoReset,@"Local\AnimusShow-"+token))
            using (EventWaitHandle exit=new EventWaitHandle(false,EventResetMode.AutoReset,@"Local\AnimusExit-"+token)) {
                if (quit) { exit.Set(); return; }
                if (!created) { show.Set(); return; }
                try { Application.Run(new TrayContext(data,background,show,exit,capture)); }
                finally { mutex.ReleaseMutex(); }
            }
        }
    }

    static class Brand {
        public static Color Bg=Color.FromArgb(10,14,20), Surface=Color.FromArgb(17,24,32),
            Border=Color.FromArgb(30,45,61), Text=Color.FromArgb(232,240,248),
            Muted=Color.FromArgb(134,154,175), Cyan=Color.FromArgb(0,212,255), Gold=Color.FromArgb(200,168,78);
        [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr handle);
        public static Color ColorFor(string state) {
            if (state=="connected") return Color.FromArgb(0,235,151);
            if (state=="syncing") return Cyan;
            if (state=="idle") return Color.FromArgb(166,143,255);
            if (state=="mcp") return Color.FromArgb(255,103,222);
            return Color.FromArgb(255,105,113);
        }
        public static string LabelFor(string state) {
            if (state=="connected") return "CONECTADO";
            if (state=="syncing") return "SINCRONIZANDO";
            if (state=="idle") return "OCIOSO";
            if (state=="mcp") return "EM USO PELO MCP";
            return "DESCONECTADO";
        }
        public static void Triangle(Graphics g, RectangleF box, Color color, double phase, bool sync) {
            g.SmoothingMode=SmoothingMode.AntiAlias;
            float x=box.X, y=box.Y, s=box.Width;
            PointF[] points={new PointF(x+s/2,y+s*.08f),new PointF(x+s*.94f,y+s*.86f),new PointF(x+s*.06f,y+s*.86f)};
            float pulse=(float)(.5+.5*Math.Sin(phase*.35));
            using (Pen glow=new Pen(Color.FromArgb((int)(25+30*pulse),color),s*.10f)) g.DrawPolygon(glow,points);
            using (Pen pen=new Pen(color,Math.Max(1.8f,s*.035f))) {pen.LineJoin=LineJoin.Round;g.DrawPolygon(pen,points);}
            PointF[] inner={new PointF(x+s*.5f,y+s*.31f),new PointF(x+s*.70f,y+s*.67f),new PointF(x+s*.30f,y+s*.67f)};
            using (Pen pen=new Pen(Color.FromArgb(170,color),Math.Max(1,s*.018f))) g.DrawPolygon(pen,inner);
            using (SolidBrush b=new SolidBrush(color)) g.FillEllipse(b,x+s*.46f,y+s*.51f,s*.08f,s*.08f);
            if (sync) {
                double p=(phase*.07)%3; int segment=(int)p; float t=(float)(p-segment);
                PointF a=points[segment],b=points[(segment+1)%3];
                using (SolidBrush light=new SolidBrush(Color.White)) g.FillEllipse(light,a.X+(b.X-a.X)*t-s*.04f,a.Y+(b.Y-a.Y)*t-s*.04f,s*.08f,s*.08f);
            }
        }
        // Icons have their own optical weights. A 64px hairline scaled to 16px
        // loses contrast; draw each target size with a minimum 1.85px stroke.
        public static Bitmap Mark(int size,Color color,int frame,bool moving,bool mcpDot,bool syncArc) {
            int scale=size<=48?8:4;
            using(Bitmap high=new Bitmap(size*scale,size*scale,System.Drawing.Imaging.PixelFormat.Format32bppArgb)) {
                using(Graphics g=Graphics.FromImage(high)) {
                    g.Clear(Color.Transparent);g.ScaleTransform(scale,scale);
                    g.SmoothingMode=SmoothingMode.AntiAlias;g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                    PointF[] p={new PointF(size*.5f,size*.13f),new PointF(size*.89f,size*.84f),new PointF(size*.11f,size*.84f)};
                    using(SolidBrush fill=new SolidBrush(Color.FromArgb(45,color)))g.FillPolygon(fill,p);
                    using(Pen pen=new Pen(color,Math.Max(1.85f,size*.075f))){pen.LineJoin=LineJoin.Round;g.DrawPolygon(pen,p);}
                    if(size<=24) {
                        PointF[] core={new PointF(size*.5f,size*.46f),new PointF(size*.64f,size*.70f),new PointF(size*.36f,size*.70f)};
                        using(SolidBrush b=new SolidBrush(color))g.FillPolygon(b,core);
                    } else {
                        PointF[] core={new PointF(size*.5f,size*.38f),new PointF(size*.69f,size*.72f),new PointF(size*.31f,size*.72f)};
                        using(Pen pen=new Pen(Color.FromArgb(235,color),Math.Max(1.25f,size*.038f))){pen.LineJoin=LineJoin.Round;g.DrawPolygon(pen,core);}
                    }
                    if(moving) {
                        double t=(frame*.07)%3;int segment=(int)t;float f=(float)(t-segment);
                        PointF a=p[segment],b=p[(segment+1)%3];float r=Math.Max(1.2f,size*.055f);
                        using(SolidBrush light=new SolidBrush(Color.White))g.FillEllipse(light,a.X+(b.X-a.X)*f-r,a.Y+(b.Y-a.Y)*f-r,r*2,r*2);
                    } else {
                        using(Pen pulse=new Pen(Color.FromArgb((int)(35+30*Math.Sin(frame*.35)),color),Math.Max(.6f,size*.018f)))g.DrawPolygon(pulse,p);
                    }
                    if(mcpDot)using(SolidBrush dot=new SolidBrush(ColorFor("mcp")))g.FillEllipse(dot,size*.73f,0,size*.25f,size*.25f);
                    if(syncArc)using(Pen arc=new Pen(Cyan,Math.Max(1.1f,size*.055f)))g.DrawArc(arc,size*.04f,size*.04f,size*.92f,size*.92f,frame*12,70);
                }
                Bitmap result=new Bitmap(size,size,System.Drawing.Imaging.PixelFormat.Format32bppArgb);
                using(Graphics g=Graphics.FromImage(result)) {
                    g.CompositingMode=CompositingMode.SourceCopy;g.CompositingQuality=CompositingQuality.HighQuality;
                    g.InterpolationMode=InterpolationMode.HighQualityBicubic;g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                    g.DrawImage(high,new Rectangle(0,0,size,size),0,0,high.Width,high.Height,GraphicsUnit.Pixel);
                }
                return result;
            }
        }
        static Icon NativeIcon(Bitmap bitmap) {
            IntPtr handle=bitmap.GetHicon();
            try{using(Icon borrowed=Icon.FromHandle(handle))return (Icon)borrowed.Clone();}
            finally{DestroyIcon(handle);}
        }
        public static Icon IconFor(string state,int frame,int size) {
            using(Bitmap bitmap=Mark(size,ColorFor(state),frame,state=="syncing" || state=="mcp",false,false))return NativeIcon(bitmap);
        }
        public static Icon ActivityIcon(Snapshot s,int frame) {
            int size=Math.Max(16,Math.Min(64,SystemInformation.SmallIconSize.Width));
            using(Bitmap bitmap=Mark(size,ColorFor(s.State),frame,s.State=="syncing" || s.State=="mcp",s.State!="mcp" && s.ActiveCalls>0,s.State=="mcp" && s.PeerState=="syncing"))return NativeIcon(bitmap);
        }
        public static byte[] IconFile() {
            int[] sizes={16,20,24,32,40,48,64,96,128,256};List<byte[]> frames=new List<byte[]>();
            foreach(int size in sizes)using(Bitmap bitmap=Mark(size,Cyan,0,false,false,false))using(MemoryStream png=new MemoryStream()) {
                bitmap.Save(png,System.Drawing.Imaging.ImageFormat.Png);frames.Add(png.ToArray());
            }
            using(MemoryStream output=new MemoryStream())using(BinaryWriter writer=new BinaryWriter(output)) {
                writer.Write((ushort)0);writer.Write((ushort)1);writer.Write((ushort)sizes.Length);
                int offset=6+16*sizes.Length;
                for(int i=0;i<sizes.Length;i++) {
                    writer.Write((byte)(sizes[i]==256?0:sizes[i]));writer.Write((byte)(sizes[i]==256?0:sizes[i]));
                    writer.Write((byte)0);writer.Write((byte)0);writer.Write((ushort)1);writer.Write((ushort)32);
                    writer.Write(frames[i].Length);writer.Write(offset);offset+=frames[i].Length;
                }
                foreach(byte[] bytes in frames)writer.Write(bytes);
                writer.Flush();return output.ToArray();
            }
        }
        public static Icon ApplicationIcon(){using(MemoryStream data=new MemoryStream(IconFile()))return new Icon(data);}
        public static void Preview(string path) {
            using(Bitmap atlas=new Bitmap(680,230))using(Graphics g=Graphics.FromImage(atlas)) {
                g.Clear(Bg);string[] states={"connected","syncing","idle","mcp","disconnected"};int[] sizes={16,24,32,48};
                using(Font font=new Font("Segoe UI",10))using(SolidBrush text=new SolidBrush(Text))for(int row=0;row<states.Length;row++) {
                    g.DrawString(LabelFor(states[row]),font,text,12,12+row*43);
                    for(int col=0;col<sizes.Length;col++)using(Bitmap icon=Mark(sizes[col],ColorFor(states[row]),8,states[row]=="mcp" || states[row]=="syncing",false,false))g.DrawImageUnscaled(icon,210+col*110,6+row*43);
                }
                atlas.Save(path,System.Drawing.Imaging.ImageFormat.Png);
            }
        }
    }

    class Snapshot {
        public Dictionary<string,object> Values=new Dictionary<string,object>();
        public string State="disconnected";
        public string PeerState="disconnected";
        public int ActiveCalls=0, ActiveClients=0;
        public bool McpRecent=false;
        public string Get(string name,string fallback) {object v;return Values.TryGetValue(name,out v)&&v!=null?Convert.ToString(v,CultureInfo.InvariantCulture):fallback;}
        public string Number(string key) {long n;return Int64.TryParse(Get(key,""),out n)?n.ToString("N0",CultureInfo.GetCultureInfo("pt-BR")):"—";}
        public static DateTime? Time(string value) {DateTime v;return DateTime.TryParse(value,CultureInfo.InvariantCulture,DateTimeStyles.RoundtripKind,out v)?(DateTime?)v.ToUniversalTime():null;}
        public static Snapshot Read(string data) {
            Snapshot s=new Snapshot();
            try {
                string path=Path.Combine(data,"peer-status.json");
                if (!File.Exists(path) || new FileInfo(path).Length>16384 || (File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0) return s;
                s.Values=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(path,Encoding.UTF8)) ?? new Dictionary<string,object>();
                DateTime? beat=Time(s.Get("heartbeat",""));
                if (!beat.HasValue || (DateTime.UtcNow-beat.Value).TotalSeconds>20 || (DateTime.UtcNow-beat.Value).TotalSeconds< -5) return s;
                int pid;
                if (!Int32.TryParse(s.Get("pid",""),out pid)) return s;
                using (Process p=Process.GetProcessById(pid)) {if(p.HasExited)return s;}
                string phase=s.Get("phase","");
                if (phase=="stopped") return s;
                if (s.Get("connection_status","")=="disconnected") return s;
                if (phase=="collecting" || phase=="syncing") s.State="syncing";
                else if (s.Get("connected","False")=="True") {
                    DateTime? success=Time(s.Get("last_success",""));
                    int interval; if(!Int32.TryParse(s.Get("interval_seconds","300"),out interval)) interval=300;
                    if (success.HasValue && (DateTime.UtcNow-success.Value).TotalSeconds<Math.Max(60,interval+90))
                        s.State=(DateTime.UtcNow-success.Value).TotalSeconds<12?"connected":"idle";
                }
            } catch (Exception) {s.State="disconnected";}
            finally {
                s.PeerState=s.State;
                s.ReadMcp(data);
                // A lost peer/hub confirmation remains the primary alert. MCP and
                // synchronization are independent secondary activities in the panel.
                if(s.State!="disconnected" && s.McpRecent)s.State="mcp";
            }
            return s;
        }
        void ReadMcp(string data) {
            try {
                HashSet<int> clients=new HashSet<int>();
                string folder=Path.Combine(data,"mcp-activity");
                if(!Directory.Exists(folder) || (File.GetAttributes(folder)&FileAttributes.ReparsePoint)!=0)return;
                foreach(string file in Directory.EnumerateFiles(folder,"*.json").Take(128)) {
                    try {
                        if(new FileInfo(file).Length>512 || (File.GetAttributes(file)&FileAttributes.ReparsePoint)!=0)continue;
                        Dictionary<string,object> row=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(file,Encoding.UTF8));
                        object rawBeat,rawPid,rawCalls;
                        if(row==null || !row.TryGetValue("heartbeat",out rawBeat) || !row.TryGetValue("pid",out rawPid) || !row.TryGetValue("active_calls",out rawCalls))continue;
                        DateTime? beat=Time(Convert.ToString(rawBeat));int pid,calls;
                        if(!beat.HasValue || (DateTime.UtcNow-beat.Value).TotalSeconds>8 || (DateTime.UtcNow-beat.Value).TotalSeconds< -5 || !Int32.TryParse(Convert.ToString(rawPid),out pid) || !Int32.TryParse(Convert.ToString(rawCalls),out calls) || calls<0 || calls>128)continue;
                        using(Process p=Process.GetProcessById(pid)){if(p.HasExited)continue;}
                        McpRecent=true;ActiveCalls+=calls;if(calls>0)clients.Add(pid);ActiveClients=clients.Count;
                    } catch(Exception){}
                }
            }catch(Exception){}
        }
    }

    class TrayContext : ApplicationContext {
        NotifyIcon tray; Icon current; Dashboard form;
        System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer();
        string data,capture; EventWaitHandle show,exit; int frame=0;
        public Snapshot Latest=new Snapshot(); public string Feedback="";
        public TrayContext(string path,bool background,EventWaitHandle open,EventWaitHandle close,string screenshot) {
            data=path;show=open;exit=close;capture=screenshot;
            form=new Dashboard(this); form.FormClosing+=(o,e)=>{if(e.CloseReason==CloseReason.UserClosing){e.Cancel=true;form.Hide();}};
            ContextMenuStrip menu=new ContextMenuStrip();
            menu.Items.Add("Abrir Animus",null,(o,e)=>Open());
            menu.Items.Add("Sincronizar agora",null,(o,e)=>Sync());
            menu.Items.Add("Iniciar peer",null,(o,e)=>StartPeer());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Sair da bandeja",null,(o,e)=>ExitThread());
            tray=new NotifyIcon {Visible=true,ContextMenuStrip=menu,Text="Animus"};
            tray.MouseClick+=(o,e)=>{if(e.Button==MouseButtons.Left)Open();};
            timer.Interval=500;timer.Tick+=(o,e)=>Tick();timer.Start();Tick();
            if(!background)Open();
        }
        void Tick() {
            if(exit.WaitOne(0)){ExitThread();return;}
            if(show.WaitOne(0))Open();
            frame++;if(frame%2==0)Latest=Snapshot.Read(data);
            timer.Interval=(Latest.State=="syncing" || Latest.State=="mcp")?120:500;
            Icon next=Brand.ActivityIcon(Latest,frame);tray.Icon=next;
            if(current!=null)current.Dispose();current=next;
            tray.Text="Animus · "+Brand.LabelFor(Latest.State);
            form.RefreshStatus(Latest,frame);
            if(capture!=null && frame>=5) {
                using(Bitmap b=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(b,new Rectangle(0,0,b.Width,b.Height));b.Save(capture,System.Drawing.Imaging.ImageFormat.Png);}
                capture=null;ExitThread();
            }
        }
        public void Open(){form.Show();form.WindowState=FormWindowState.Normal;form.Activate();}
        public void Sync() {
            try {
                if(!Directory.Exists(data)){Feedback="Configure o peer antes de sincronizar.";return;}
                string dest=Path.Combine(data,"peer-command.json"),temp=dest+".desktop-tmp";
                if((File.Exists(dest)&&(File.GetAttributes(dest)&FileAttributes.ReparsePoint)!=0) || (File.Exists(temp)&&(File.GetAttributes(temp)&FileAttributes.ReparsePoint)!=0)) return;
                File.WriteAllText(temp,"{\"action\":\"sync\"}",new UTF8Encoding(false));
                if(File.Exists(dest))File.Replace(temp,dest,null);else File.Move(temp,dest);
                Feedback="Sincronização solicitada. O peer conclui o ciclo em andamento.";
            }catch(Exception){Feedback="Não foi possível solicitar. Verifique se o peer está instalado.";}
        }
        public void StartPeer() {
            try {
                ProcessStartInfo info=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"schtasks.exe"),"/Run /TN AnimusPeerDaemon");
                info.UseShellExecute=false;info.CreateNoWindow=true;info.RedirectStandardOutput=true;info.RedirectStandardError=true;
                Process p=Process.Start(info);p.BeginOutputReadLine();p.BeginErrorReadLine();p.EnableRaisingEvents=true;p.Exited+=(o,e)=>p.Dispose();
                Feedback="Inicialização solicitada ao Windows. Aguarde a conexão do peer.";
            } catch(Exception){Feedback="Instale o serviço do peer para iniciá-lo pela bandeja.";}
        }
        public void OpenFolder(){try{Process.Start(new ProcessStartInfo("explorer.exe", "\""+data+"\""){UseShellExecute=true});}catch(Exception){Feedback="Pasta local indisponível.";}}
        public void OpenCredit(string url) {
            // Fixed public destinations only. Never read a URL from IPC/config.
            if(url!="https://datano.com.br/animus" && url!="https://github.com/GuilhermeP96/animus")return;
            try {Process.Start(new ProcessStartInfo(url){UseShellExecute=true});}
            catch(Exception){Feedback="Não foi possível abrir o navegador.";}
        }
        protected override void ExitThreadCore(){timer.Stop();tray.Visible=false;tray.Dispose();if(current!=null)current.Dispose();form.Dispose();timer.Dispose();base.ExitThreadCore();}
    }

    class CreditLink : Button {
        public readonly string Url;
        string heading,caption; Image mark; bool hover;
        public CreditLink(string title,string subtitle,string url,Image logo,Action<string> open) {
            heading=title;caption=subtitle;Url=url;mark=logo;
            FlatStyle=FlatStyle.Flat;FlatAppearance.BorderSize=0;Cursor=Cursors.Hand;
            BackColor=Brand.Surface;ForeColor=Brand.Text;TabStop=true;
            AccessibleName=title+" — "+subtitle;AccessibleDescription=url;AccessibleRole=AccessibleRole.Link;
            SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer,true);
            MouseEnter+=(o,e)=>{hover=true;Invalidate();};MouseLeave+=(o,e)=>{hover=false;Invalidate();};
            GotFocus+=(o,e)=>Invalidate();LostFocus+=(o,e)=>Invalidate();
            Click+=(o,e)=>open(Url);
        }
        protected override void OnPaint(PaintEventArgs e) {
            Graphics g=e.Graphics;g.SmoothingMode=SmoothingMode.AntiAlias;
            Rectangle box=new Rectangle(0,0,Width-1,Height-1);
            using(LinearGradientBrush background=new LinearGradientBrush(box,hover?Color.FromArgb(21,48,61):Color.FromArgb(18,30,42),Brand.Surface,20))g.FillRectangle(background,box);
            using(Pen border=new Pen(hover||Focused?Brand.Cyan:Brand.Border,1))g.DrawRectangle(border,box);
            using(SolidBrush halo=new SolidBrush(Color.FromArgb(20,Brand.Cyan)))g.FillEllipse(halo,7,10,38,38);
            if(mark!=null) {
                g.InterpolationMode=InterpolationMode.HighQualityBicubic;g.DrawImage(mark,new Rectangle(10,13,32,32));
            } else {
                using(Font code=new Font("Consolas",12,FontStyle.Bold))using(SolidBrush ink=new SolidBrush(Brand.Text))g.DrawString("</>",code,ink,8,18);
            }
            using(Font title=new Font("Segoe UI",10,FontStyle.Bold))using(SolidBrush ink=new SolidBrush(hover?Color.White:Brand.Cyan))g.DrawString(heading,title,ink,52,9);
            using(Font subtitle=new Font("Segoe UI",8))using(SolidBrush ink=new SolidBrush(Brand.Muted))g.DrawString(caption,subtitle,ink,52,31);
            using(Pen arrow=new Pen(hover?Color.White:Brand.Muted,1.3f)) {
                float x=Width-18,y=14;g.DrawLine(arrow,x-5,y+6,x+2,y-1);g.DrawLine(arrow,x-4,y-1,x+2,y-1);g.DrawLine(arrow,x+2,y-1,x+2,y+5);
            }
        }
    }

    class Dashboard : Form {
        TrayContext app; Snapshot snapshot=new Snapshot(); int frame;
        Image datanoMark;
        Label state,description,version,lastSync,lastCycle,feedback,connection;
        Label[] values=new Label[3]; ListBox activity;
        public Dashboard(TrayContext context) {
            app=context;Text="Animus · Memória em movimento";BackColor=Brand.Bg;ForeColor=Brand.Text;
            Font=new Font("Segoe UI",10);ClientSize=new Size(1020,700);MinimumSize=new Size(960,720);
            StartPosition=FormStartPosition.CenterScreen;DoubleBuffered=true;
            Icon=Brand.ApplicationIcon();MaximizeBox=false;
            AddLabel("A N I M U S",30,35,215,40,25,Brand.Text);
            AddLabel("MEMORY SYNCHRONIZATION",32,82,210,20,8,Brand.Muted);
            AddLabel("◈   Visão geral",32,162,204,35,12,Brand.Cyan);
            AddLabel("Sua memória, conectada.",32,404,205,25,11,Brand.Text);
            AddLabel("CRÉDITOS",32,448,210,20,8,Brand.Gold);
            AddLabel("Guilherme Pinheiro",32,472,210,23,10,Brand.Text);
            using(Stream logo=System.Reflection.Assembly.GetExecutingAssembly().GetManifestResourceStream("AnimusDesktop.Datano.png"))
            using(Image image=Image.FromStream(logo))datanoMark=new Bitmap(image);
            Controls.Add(new CreditLink("Datano","Página do Animus","https://datano.com.br/animus",datanoMark,app.OpenCredit){Left=26,Top=510,Width=206,Height=58});
            Controls.Add(new CreditLink("GitHub","Código e contribuições","https://github.com/GuilhermeP96/animus",null,app.OpenCredit){Left=26,Top=579,Width=206,Height=58});
            AddLabel("OPEN SOURCE · AGPL-3.0",32,657,210,20,8,Brand.Muted);
            AddLabel("CENTRAL DO PEER",288,30,400,22,9,Brand.Gold);
            AddLabel("Memória em movimento.",286,62,680,45,27,Brand.Text);
            AddLabel("Uma visão do seu Animus, sem interromper o seu fluxo.",289,111,680,28,11,Brand.Muted);
            state=AddLabel("CONECTANDO",460,171,490,32,19,Brand.Cyan);
            description=AddLabel("Aguardando o primeiro sinal do peer.",462,211,480,25,10,Brand.Muted);
            connection=AddLabel("",462,242,480,23,10,Brand.Muted);
            string[] names={"MEMÓRIAS LOCAIS","NA FILA DE ENVIO","WORKSPACES"};
            for(int i=0;i<3;i++) {
                int left=289+i*232;
                AddLabel(names[i],left+18,322,210,25,8,Brand.Muted);
                values[i]=AddLabel("—",left+18,352,202,48,28,Brand.Text);
            }
            AddLabel("ATIVIDADE RECENTE",289,432,440,24,9,Brand.Gold);
            activity=new ListBox {Left=289,Top=468,Width=690,Height=105,BorderStyle=BorderStyle.None,
                BackColor=Brand.Bg,ForeColor=Brand.Muted,Font=new Font("Segoe UI",10),SelectionMode=SelectionMode.None,AccessibleName="Atividade recente do peer"};
            Controls.Add(activity);
            lastSync=AddLabel("Última conexão: —",289,582,450,21,9,Brand.Muted);
            lastCycle=AddLabel("Último ciclo: —",289,605,450,21,9,Brand.Muted);
            version=AddLabel("",787,605,195,21,9,Brand.Muted);
            AddButton("Sincronizar agora",289,645,170,(o,e)=>app.Sync());
            AddButton("Iniciar peer",471,645,130,(o,e)=>app.StartPeer());
            AddButton("Pasta local",613,645,130,(o,e)=>app.OpenFolder());
            feedback=AddLabel("",752,641,231,48,8,Brand.Muted);
        }
        Label AddLabel(string text,int x,int y,int width,int height,float size,Color color) {
            Label l=new Label {Text=text,Left=x,Top=y,Width=width,Height=height,ForeColor=color,
                BackColor=Color.Transparent,Font=new Font("Segoe UI",size),AccessibleName=text};Controls.Add(l);return l;
        }
        void AddButton(string text,int x,int y,int width,EventHandler handler) {
            Button b=new Button {Text=text,Left=x,Top=y,Width=width,Height=36,FlatStyle=FlatStyle.Flat,
                BackColor=Brand.Surface,ForeColor=Brand.Cyan,Cursor=Cursors.Hand,AccessibleName=text};
            b.FlatAppearance.BorderColor=Brand.Border;b.Click+=handler;Controls.Add(b);
        }
        string LocalTime(string name) {DateTime? t=Snapshot.Time(snapshot.Get(name,""));return t.HasValue?t.Value.ToLocalTime().ToString("dd/MM HH:mm:ss"):"—";}
        public void RefreshStatus(Snapshot value,int tick) {
            snapshot=value;frame=tick;state.Text=Brand.LabelFor(value.State);state.ForeColor=Brand.ColorFor(value.State);
            description.Text=value.State=="mcp"?(value.ActiveCalls>0?value.ActiveCalls+" chamada(s) ativa(s) · "+value.ActiveClients+" processo(s) MCP":"Chamada concluída · retornando ao estado do peer."):
                value.State=="syncing"?(value.Get("phase","")=="collecting"?"Organizando as memórias deste dispositivo.":"Trocando memórias com o hub autenticado."):
                value.State=="idle"?"Tudo em seu ritmo. Aguardando o próximo ciclo.":value.State=="connected"?"Conexão autenticada confirmada pelo peer.":"Sem conexão confirmada. Suas memórias permanecem locais.";
            connection.Text=value.State=="mcp"?(value.PeerState=="syncing"?"● Sincronização também em andamento":"● Hub conectado · acesso local pelo MCP"):
                value.State=="disconnected"?(value.ActiveCalls>0?"● MCP local ativo: "+value.ActiveCalls+" chamada(s) · hub desconectado":"O peer tenta novamente no próximo ciclo."):
                value.State=="idle"?"● Conectado ao hub · em segundo plano":"● Peer em execução · sincronização protegida";
            values[0].Text=value.Number("total_memories");values[1].Text=value.Number("unsynced");values[2].Text=value.Number("workspaces");
            lastSync.Text="Última conexão: "+LocalTime("last_success");lastCycle.Text="Último ciclo: "+LocalTime("last_cycle");
            version.Text="Peer "+value.Get("version","—")+" · Desktop 0.9.2";feedback.Text=app.Feedback;
            activity.BeginUpdate();activity.Items.Clear();
            object raw;
            if(value.Values.TryGetValue("events",out raw) && raw is IEnumerable) {
                foreach(object item in (IEnumerable)raw) {
                    Dictionary<string,object> entry=item as Dictionary<string,object>; if(entry==null)continue;
                    object eventCode,eventTime;
                    if(!entry.TryGetValue("code",out eventCode) || !entry.TryGetValue("at",out eventTime))continue;
                    string code=Convert.ToString(eventCode),label=null;
                    switch(code) {
                        case "starting":label="Peer iniciado em segundo plano";break;
                        case "collect":label="Coleta local em andamento";break;
                        case "push_ok":label="Envio autenticado concluído";break;
                        case "pull_ok":label="Conexão e recebimento confirmados";break;
                        case "cycle_complete":label="Ciclo de memória concluído";break;
                        case "hub_unavailable":label="Hub indisponível · nova tentativa no próximo ciclo";break;
                        case "cycle_error":label="Ciclo interrompido · consulte o diagnóstico local";break;
                        case "stopped":label="Peer encerrado";break;
                    }
                    DateTime? t=Snapshot.Time(Convert.ToString(eventTime));
                    if(label!=null)activity.Items.Add((t.HasValue?t.Value.ToLocalTime().ToString("HH:mm:ss"):"—")+"    "+label);
                }
            }
            if(activity.Items.Count==0)activity.Items.Add("Aguardando atividade do peer local.");
            activity.EndUpdate();if(Visible)Invalidate();
        }
        protected override void OnPaint(PaintEventArgs e) {
            base.OnPaint(e);Graphics g=e.Graphics;g.SmoothingMode=SmoothingMode.AntiAlias;
            using(SolidBrush surface=new SolidBrush(Brand.Surface))g.FillRectangle(surface,0,0,258,ClientSize.Height);
            using(Pen border=new Pen(Brand.Border)) {
                g.DrawLine(border,258,0,258,ClientSize.Height);
                for(int i=0;i<3;i++)g.DrawRectangle(border,289+i*232,307,220,103);
                g.DrawRectangle(border,289,155,684,133);
            }
            using(Pen grid=new Pen(Color.FromArgb(18,Brand.Cyan)))for(int i=0;i<9;i++)g.DrawLine(grid,298+i*18,164,298+i*18,279);
            Brand.Triangle(g,new RectangleF(316,165,116,116),Brand.ColorFor(snapshot.State),frame,snapshot.State=="syncing" || snapshot.State=="mcp");
            if(snapshot.State=="mcp" && snapshot.PeerState=="syncing")using(Pen ring=new Pen(Brand.Cyan,2))g.DrawArc(ring,308,162,132,122,frame*12,80);
        }
        protected override void Dispose(bool disposing) {
            base.Dispose(disposing);
            if(disposing && datanoMark!=null){datanoMark.Dispose();datanoMark=null;}
        }
    }
}
