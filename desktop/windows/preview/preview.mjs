import mermaid from './vendor/mermaid/mermaid.esm.min.mjs';

const host=window.chrome?.webview;
const send=value=>host?.postMessage(value);
const content=document.getElementById('content');
const modal=document.getElementById('expanded');
const metrics={tables:0,diagrams:0,diagramErrors:0,code:0,images:0,math:0};
let generation=0,documentId=0,imageCounter=0,documentScale=1;
const imageRequests=new Map();
const observers=new Set();
const esc=value=>parser.utils.escapeHtml(String(value));
const slug=value=>String(value).normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^\p{L}\p{N}_-]+/gu,'-').replace(/^-|-$/g,'');
const parser=window.markdownit({html:false,linkify:true,typographer:false,breaks:false});
parser.use(window.markdownitFootnote).use(window.markdownitTaskLists,{enabled:false});
parser.inline.ruler.before('link','obsidian',function(state,silent){
  const start=state.pos;const embed=state.src.startsWith('![[',start);
  if(!embed&&!state.src.startsWith('[[',start))return false;
  const from=start+(embed?3:2),end=state.src.indexOf(']]',from);if(end<0||end-from>2000)return false;
  if(!silent){const token=state.push('html_inline','',0);const parts=state.src.slice(from,end).split('|');const target=parts[0];
    token.content=embed?`<span class="attachment-placeholder" data-note-image="${esc(target)}">Imagem: ${esc(target)}</span>`:
      `<a class="wikilink" href="#" data-note-link="${esc(target)}">${esc(parts[1]||target)}</a>`;}
  state.pos=end+2;return true;
});
parser.renderer.rules.image=(tokens,index)=>{
  const t=tokens[index],src=t.attrGet('src')||'',alt=t.content||'';
  return `<span class="attachment-placeholder" data-note-image="${esc(src)}" data-alt="${esc(alt)}">Imagem: ${esc(alt||src)}</span>`;
};
parser.renderer.rules.heading_open=(tokens,index,options,env,self)=>{
  const text=tokens[index+1]?.content||'';let id=slug(text)||'secao';env.ids??=new Set();
  const base=id;let n=2;while(env.ids.has(id))id=base+'-'+n++;env.ids.add(id);tokens[index].attrSet('id',id);
  return self.renderToken(tokens,index,options);
};
mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'dark',htmlLabels:false,
  maxTextSize:50000,maxEdges:2000,flowchart:{htmlLabels:false},
  secure:['securityLevel','startOnLoad','maxTextSize','maxEdges','htmlLabels','flowchart','themeCSS','themeVariables']});

function button(text,label,action){const b=document.createElement('button');b.type='button';b.textContent=text;b.title=label;b.setAttribute('aria-label',label);b.addEventListener('click',action);return b;}
async function copy(text){try{await navigator.clipboard.writeText(text);}catch{send({type:'copy',text:String(text).slice(0,524288),doc:documentId});}}
function cleanSvg(text){
  const safe=DOMPurify.sanitize(text,{USE_PROFILES:{svg:true,svgFilters:true},FORBID_TAGS:['foreignObject','script','image','a']});
  const node=new DOMParser().parseFromString(safe,'image/svg+xml').documentElement;
  if(node.localName!=='svg'||node.querySelector('parsererror'))throw new Error('SVG inválido');
  node.querySelectorAll('*').forEach(element=>{
    [...element.attributes].forEach(a=>{if(/href$/i.test(a.name)&&!a.value.startsWith('#'))element.removeAttribute(a.name);
      else if(/(?:url\s*\(|@import|expression\s*\()/i.test(a.value)&&!/^url\(\s*#[\w:-]+\s*\)$/.test(a.value))element.removeAttribute(a.name);});
    if(element.localName==='style')element.textContent=element.textContent.replace(/@import[^;]*;?/gi,'').replace(/url\(\s*(['"]?)(?!#)[^)]+\)/gi,'none');
  });
  return document.importNode(node,true);
}
function objectViewer(element,label,{source='',svg=false}={}){
  const card=document.createElement('section');card.className=svg?'diagram-card':'image-card';
  const tools=document.createElement('div');tools.className='object-tools';const title=document.createElement('strong');title.textContent=label;tools.append(title);
  const viewport=document.createElement('div');viewport.className='viewport';viewport.tabIndex=0;viewport.setAttribute('aria-label',label+' — arraste para mover; mais, menos e Home controlam o zoom');
  const inner=document.createElement('div');inner.className='viewport-content';inner.append(element);viewport.append(inner);
  const scaleLabel=document.createElement('output');scaleLabel.className='object-scale';scaleLabel.setAttribute('aria-live','polite');
  let x=0,y=0,s=1,drag=null,width=1,height=1;
  function dimensions(){if(svg){const box=element.viewBox?.baseVal;width=box?.width||parseFloat(element.getAttribute('width'))||800;height=box?.height||parseFloat(element.getAttribute('height'))||400;element.setAttribute('width',width);element.setAttribute('height',height);}else{width=element.naturalWidth||640;height=element.naturalHeight||360;element.width=width;element.height=height;}}
  function apply(){inner.style.transform=`translate(${x}px,${y}px) scale(${s})`;scaleLabel.value=Math.round(s*100)+'%';scaleLabel.textContent=scaleLabel.value;card.dataset.scale=String(s);card.dataset.panX=String(x);card.dataset.panY=String(y);}
  function zoom(next,px=viewport.clientWidth/2,py=viewport.clientHeight/2){next=Math.min(12,Math.max(.05,next));const ratio=next/s;x=px-(px-x)*ratio;y=py-(py-y)*ratio;s=next;apply();}
  function fit(){dimensions();s=Math.min((viewport.clientWidth-24)/width,(viewport.clientHeight-24)/height,1);s=Math.max(.05,s);x=(viewport.clientWidth-width*s)/2;y=(viewport.clientHeight-height*s)/2;apply();}
  tools.append(button('−','Diminuir diagrama ou imagem',()=>zoom(s/1.25)),scaleLabel,button('+','Ampliar diagrama ou imagem',()=>zoom(s*1.25)),button('Ajustar','Ajustar à tela',fit),button('1:1','Tamanho original',()=>{s=1;x=12;y=12;apply();}));
  tools.append(button('Ampliar','Abrir objeto em área ampliada',()=>expandObject(element,label,{source,svg})));
  if(source)tools.append(button('Copiar código','Copiar código Mermaid',()=>copy(source)));
  if(svg)tools.append(button('SVG','Exportar diagrama SVG',()=>send({type:'export-svg',doc:documentId,value:new XMLSerializer().serializeToString(cleanSvg(new XMLSerializer().serializeToString(element)))})));
  viewport.addEventListener('pointerdown',e=>{if(e.button!==0)return;viewport.focus();viewport.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY,baseX:x,baseY:y,ratio:viewport.getBoundingClientRect().width/viewport.clientWidth||1};viewport.classList.add('dragging');});
  viewport.addEventListener('pointermove',e=>{if(!drag)return;x=drag.baseX+(e.clientX-drag.x)/drag.ratio;y=drag.baseY+(e.clientY-drag.y)/drag.ratio;apply();});
  const end=()=>{drag=null;viewport.classList.remove('dragging');};viewport.addEventListener('pointerup',end);viewport.addEventListener('pointercancel',end);
  viewport.addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.altKey)return;e.preventDefault();const box=viewport.getBoundingClientRect(),ratio=box.width/viewport.clientWidth||1;zoom(s*Math.exp(-e.deltaY*.002),(e.clientX-box.left)/ratio,(e.clientY-box.top)/ratio);},{passive:false});
  viewport.addEventListener('dblclick',fit);
  viewport.addEventListener('keydown',e=>{if(['+','=','-','Home','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();if(e.key==='+'||e.key==='=')zoom(s*1.25);else if(e.key==='-')zoom(s/1.25);else if(e.key==='Home'||e.key==='0')fit();else{x+=e.key==='ArrowLeft'?30:e.key==='ArrowRight'?-30:0;y+=e.key==='ArrowUp'?30:e.key==='ArrowDown'?-30:0;apply();}}});
  const hint=document.createElement('div');hint.className='object-hint';hint.textContent='Arraste para mover · Ctrl + roda para zoom · duplo clique ou Home para ajustar';
  card.append(tools,viewport,hint);requestAnimationFrame(fit);const observer=new ResizeObserver(()=>{if(!drag)fit();});observer.observe(viewport);observers.add(observer);card.disposeViewer=()=>{observer.disconnect();observers.delete(observer);};return card;
}
function clearExpanded(){const target=document.getElementById('expanded-body');target.querySelectorAll('.diagram-card,.image-card').forEach(c=>c.disposeViewer?.());target.replaceChildren();}
function expandObject(element,label,options){const target=document.getElementById('expanded-body');clearExpanded();target.replaceChildren(objectViewer(element.cloneNode(true),label,options));document.getElementById('expanded-title').textContent=label;modal.showModal();}
function tables(){content.querySelectorAll('table').forEach(table=>{metrics.tables++;const card=document.createElement('section');card.className='table-card';const tools=document.createElement('div');tools.className='table-tools';const scroll=document.createElement('div');scroll.className='table-scroll';
  tools.append(button('Ampliar tabela','Abrir tabela em área ampliada',()=>{document.getElementById('expanded-title').textContent='Tabela';const wrapper=document.createElement('div');wrapper.className='table-scroll';wrapper.append(table.cloneNode(true));document.getElementById('expanded-body').replaceChildren(wrapper);modal.showModal();}),
    button('Copiar CSV','Copiar tabela como CSV',()=>copy([...table.rows].map(r=>[...r.cells].map(c=>'"'+c.innerText.replace(/^[=+@\-\t\r]/,"'$&").replace(/"/g,'""')+'"').join(',')).join('\r\n'))));table.replaceWith(card);scroll.append(table);card.append(tools,scroll);});}
function callouts(){content.querySelectorAll('blockquote').forEach(quote=>{const p=quote.querySelector(':scope > p');const first=p?.firstChild;if(!first||first.nodeType!==Node.TEXT_NODE)return;const match=first.textContent.match(/^\[!([a-z]+)\]([+-])?\s*([^\n]*)/i);if(!match)return;const label=match[3]||match[1].toUpperCase();first.textContent=first.textContent.slice(match[0].length);quote.classList.add('callout');quote.dataset.kind=match[1].toLowerCase();if(match[2]){const details=document.createElement('details');details.open=match[2]==='+';const summary=document.createElement('summary');summary.textContent=label;details.append(summary,...quote.childNodes);quote.replaceChildren(details);}else{const title=document.createElement('div');title.className='callout-title';title.textContent=label;quote.prepend(title);}});}
async function codeBlocks(ticket){let index=0;for(const code of [...content.querySelectorAll('pre>code')]){if(ticket!==generation)return;const source=code.textContent;const language=([...code.classList].find(c=>c.startsWith('language-'))||'').slice(9);
  if(language.toLowerCase()==='mermaid'){try{const result=await mermaid.render('animusDiagram'+ticket+'_'+index++,source);if(ticket!==generation)return;const svg=cleanSvg(result.svg);code.parentElement.replaceWith(objectViewer(svg,'Mermaid · diagrama',{source,svg:true}));metrics.diagrams++;}catch{metrics.diagramErrors++;const error=document.createElement('div');error.className='render-error';error.textContent='Não foi possível renderizar este diagrama. O código original foi preservado abaixo.';code.parentElement.before(error);}continue;}
  metrics.code++;if(language&&hljs.getLanguage(language))hljs.highlightElement(code);
  const card=document.createElement('section');card.className='code-card';const tools=document.createElement('div');tools.className='code-tools';const label=document.createElement('small');label.textContent=language||'código';tools.append(label,button('Copiar','Copiar bloco de código',()=>copy(source)),button('Quebrar linhas','Alternar quebra de linhas',()=>card.classList.toggle('wrap')));const pre=code.parentElement;pre.replaceWith(card);card.append(tools,pre);
}}
function images(){content.querySelectorAll('[data-note-image]').forEach(placeholder=>{metrics.images++;const target=placeholder.dataset.noteImage,id='image'+(++imageCounter);const img=new Image();img.alt=placeholder.dataset.alt||target;
  const done=data=>{img.onload=()=>placeholder.replaceWith(objectViewer(img,'Imagem'));img.onerror=()=>{placeholder.textContent='Imagem não disponível ou formato inválido.';};img.src=data;};
  if(/^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(target)&&target.length<3*1024*1024){done(target);return;}
  if(/^[a-z][a-z\d+.-]*:/i.test(target)||target.startsWith('//')){placeholder.textContent='Imagem externa bloqueada. Nenhum conteúdo foi carregado automaticamente.';return;}
  imageRequests.set(id,{done,placeholder,doc:documentId});send({type:'image',doc:documentId,id,reference:target});});}
async function render(message){const ticket=++generation;documentId=message.doc;imageRequests.clear();document.getElementById('doc-expand').hidden=!message.can_expand;if(modal.open)modal.close();for(const observer of observers)observer.disconnect();observers.clear();Object.keys(metrics).forEach(k=>metrics[k]=0);
  try{const html=parser.render(String(message.markdown||''),{});content.innerHTML=DOMPurify.sanitize(html,{FORBID_TAGS:['script','style','iframe','object','embed','form'],FORBID_ATTR:['srcdoc'],ADD_ATTR:['data-note-image','data-note-link','data-alt']});
    callouts();tables();images();
    renderMathInElement(content,{throwOnError:false,trust:false,strict:'warn',delimiters:[{left:'$$',right:'$$',display:true},{left:'\\[',right:'\\]',display:true},{left:'$',right:'$',display:false},{left:'\\(',right:'\\)',display:false}]});metrics.math=content.querySelectorAll('.katex').length;
    await codeBlocks(ticket);if(ticket!==generation)return;
    document.getElementById('summary').textContent=`${metrics.tables} tabela(s) · ${metrics.diagrams} diagrama(s)`;window.animusPreviewMetrics={...metrics};
    send({type:'rendered',doc:documentId,...metrics});if(message.fragment){const id=message.fragment;(document.getElementById(id)||document.getElementById(slug(id)))?.scrollIntoView();}
  }catch{content.replaceChildren();const error=document.createElement('p');error.className='render-error';error.textContent='A prévia não pôde ser concluída. O Markdown original permanece no editor.';content.append(error);send({type:'render-error',doc:documentId});}
}
content.addEventListener('click',e=>{const anchor=e.target.closest('a');if(!anchor)return;e.preventDefault();const wiki=anchor.dataset.noteLink,href=anchor.getAttribute('href')||'';
  if(wiki){const [reference,fragment='']=wiki.split('#',2);if(!reference){(document.getElementById(fragment)||document.getElementById(slug(fragment)))?.scrollIntoView();}else send({type:'open-note',doc:documentId,reference,fragment});return;}
  if(href.startsWith('#')){const id=decodeURIComponent(href.slice(1));(document.getElementById(id)||document.getElementById(slug(id)))?.scrollIntoView();return;}
  if(/^https?:\/\//i.test(href))send({type:'external',doc:documentId,url:href});else if(/\.md(?:#|$)/i.test(href)){const [reference,fragment='']=href.split('#',2);send({type:'open-note',doc:documentId,reference,fragment});}});
function docZoom(next){documentScale=Math.max(.5,Math.min(2.5,next));content.style.zoom=String(documentScale);document.getElementById('doc-scale').value=Math.round(documentScale*100)+'%';}
document.getElementById('doc-in').onclick=()=>docZoom(documentScale+.1);document.getElementById('doc-out').onclick=()=>docZoom(documentScale-.1);document.getElementById('doc-reset').onclick=()=>docZoom(1);
document.getElementById('doc-expand').onclick=()=>send({type:'expand-document',doc:documentId});
document.getElementById('close-expanded').onclick=()=>modal.close();
modal.addEventListener('close',clearExpanded);
host?.addEventListener('message',event=>{const m=event.data;if(m?.type==='render')render(m);else if(m?.type==='image-result'){const request=imageRequests.get(m.id);if(!request||request.doc!==m.doc)return;imageRequests.delete(m.id);if(m.data_url)request.done(m.data_url);else request.placeholder.textContent='Anexo não disponível nesta fonte canônica.';}});
document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key.toLowerCase()==='s')e.preventDefault();});
send({type:'ready'});
