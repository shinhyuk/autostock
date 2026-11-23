"""결과 페이지의 가격 차트 스크립트 (의존성 없는 SVG). 10초마다 /data 를 다시 불러 그린다."""
CHART_JS = r"""
(()=>{const box=document.getElementById('chart');if(!box)return;
const q=new URLSearchParams(location.search),K=q.get('k'),M=box.dataset.mode;let sym=box.dataset.sym,D=null,hv=null,span=120;
try{span=+(localStorage.getItem('span')||120)}catch(e){}
const NS='http://www.w3.org/2000/svg',el=(n,a,t)=>{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(t!=null)e.textContent=t;return e};
const hm=t=>new Date(t).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Seoul'});
const usd=v=>'$'+(Math.abs(v)<100?v.toFixed(2):v.toFixed(2)),won=v=>Math.round(v).toLocaleString('ko-KR')+'원';
const tip=document.getElementById('tip'),msg=document.getElementById('cmsg');
const LC={entry:'var(--mut)',stop:'var(--dn)',take:'var(--up)',trail:'var(--warn)',rng:'var(--warn)',box:'var(--mut)',bxl:'var(--up)',bxs:'var(--dn)',noise:'var(--noise)'};
async function load(){try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=${M}&sym=${sym}&span=${span}${window.chartQ||''}`);D=await r.json()}catch(e){D={error:'연결 실패'}}if(window.onChart)window.onChart(D);draw()}
window.chartReload=load;
function draw(){box.innerHTML='';const b=(D&&D.bars)||[];
 if(b.length<2){msg.textContent=(D&&D.error)?'차트를 불러오지 못했습니다: '+D.error:'표시할 시세가 아직 없습니다 (봇이 1분봉을 모으는 중)';tip.style.display='none';return}
 const n=b.length,W=box.clientWidth,H=320,pl=4,pr=58,pt=10,ph=220,vt=pt+ph+8,vh=50,pb=22,pw=W-pl-pr,step=pw/n;
 const mk=D.marks||[],ln=D.lines||[],rg=D.range||[],vw=D.vwap||[];
 let lo=Math.min(...b.map(x=>x[3])),hi=Math.max(...b.map(x=>x[2]));
 const pad=(hi-lo)*.06||.05;const inR=v=>v>=lo-(hi-lo)*.6&&v<=hi+(hi-lo)*.6;
 for(const v of [...rg,...ln.filter(l=>l.k!='take'||inR(l.v)).map(l=>l.v),...mk.map(m=>m.p)])if(inR(v)){lo=Math.min(lo,v);hi=Math.max(hi,v)}
 lo-=pad;hi+=pad;const X=i=>pl+(i+.5)*step,Y=v=>pt+(hi-v)/(hi-lo)*ph,idx=t=>{let k=0;for(let i=0;i<n;i++){if(b[i][0]<=t)k=i;else break}return k};
 const s=el('svg',{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':sym+' 1분봉 차트와 매매 지점'});
 const tags=[...ln.filter(l=>inR(l.v)).map(l=>Y(l.v)),Y(b[n-1][4])];
 for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,y=Y(v);s.append(el('line',{x1:pl,x2:W-pr,y1:y,y2:y,stroke:'var(--line)','stroke-width':1}));if(tags.every(t=>Math.abs(t-y)>15))s.append(el('text',{x:W-pr+6,y:y+4,'font-size':11,fill:'var(--mut)'},usd(v)))}
 const nt=W<420?3:5;for(let i=0;i<nt;i++){const k=Math.round((n-1)*i/(nt-1));s.append(el('text',{x:X(k),y:H-6,'font-size':11,fill:'var(--mut)','text-anchor':i==0?'start':i==nt-1?'end':'middle'},hm(b[k][0])))}
 const vs=b.map(x=>x[5]||0).sort((a,b)=>a-b),vmax=vs[Math.floor(vs.length*.95)]||vs[vs.length-1]||1;
 for(let i=0;i<n;i++){const [t,o,h,l,c,v]=b[i],up=c>=o,col=up?'var(--up)':'var(--dn)',vh2=Math.min((v||0)/vmax,1)*vh;
  s.append(el('rect',{x:X(i)-Math.max(step*.35,.5),y:vt+vh-vh2,width:Math.max(step*.7,1),height:vh2,fill:col,opacity:.35}))}
 if(rg.length==2){const y1=Y(rg[1]),y2=Y(rg[0]);s.append(el('rect',{x:pl,y:y1,width:pw,height:Math.max(y2-y1,1),fill:'var(--warn)',opacity:.07}))}
 for(const bd of (D.bands||[])){const y1=Y(bd.hi),y2=Y(bd.lo);s.append(el('rect',{x:pl,y:y1,width:pw,height:Math.max(y2-y1,1),fill:bd.k=='bl'?'var(--up)':'var(--dn)',opacity:.13}))}
 if(step>=3){for(let i=0;i<n;i++){const [t,o,h,l,c]=b[i],col=c>=o?'var(--up)':'var(--dn)',w=Math.max(step*.62,1.5);
   s.append(el('line',{x1:X(i),x2:X(i),y1:Y(h),y2:Y(l),stroke:col,'stroke-width':1}),el('rect',{x:X(i)-w/2,y:Math.min(Y(o),Y(c)),width:w,height:Math.max(Math.abs(Y(o)-Y(c)),1),fill:col,rx:1}))}}
 else{s.append(el('path',{d:b.map((x,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(x[4]).toFixed(1)).join(''),fill:'none',stroke:'var(--fg)','stroke-width':1.6,'stroke-linejoin':'round',opacity:.85}))}
 const vp=vw.map((v,i)=>v==null?null:[X(i),Y(v)]).filter(Boolean);if(vp.length>1)s.append(el('path',{d:vp.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(''),fill:'none',stroke:'var(--vwap)','stroke-width':1.6,opacity:.9}));
 // 선은 실제 가격 위치에, 가격표·이름은 겹치지 않게 위아래로 비켜 그린다 (현재가 표는 고정)
 const vis=ln.filter(l=>inR(l.v)).map(l=>({...l,y:Y(l.v)})).sort((a,c)=>a.y-c.y),outs=ln.filter(l=>!inR(l.v));
 outs.forEach((l,k)=>s.append(el('text',{x:W-pr-4,y:pt+12+k*13,'font-size':11,fill:LC[l.k],'text-anchor':'end'},l.l+' '+usd(l.v)+' ↑')));
 const curY=Y(b[n-1][4]),spread=(arr,gap,fixed)=>{let prev=-1e9;for(const a of arr){a.ty=Math.max(a.y,prev+gap);if(fixed!=null&&Math.abs(a.ty-fixed)<gap)a.ty=fixed+gap;prev=a.ty}
  const over=arr.length?arr[arr.length-1].ty-(pt+ph+8):0;if(over>0)for(const a of arr)a.ty-=over;};
 spread(vis,17,curY);
 const lab=vis.map(a=>({...a,y:a.y-4}));spread(lab,13,null);
 for(const [k,l] of vis.entries()){
  s.append(el('line',{x1:pl,x2:W-pr,y1:l.y,y2:l.y,stroke:LC[l.k],'stroke-width':1.5,'stroke-dasharray':l.k=='entry'?'2 3':l.k=='box'||l.k=='bxl'||l.k=='bxs'?'2 4':'6 4'}));
  if(Math.abs(l.ty-l.y)>1)s.append(el('line',{x1:W-pr-6,x2:W-pr+1,y1:l.y,y2:l.ty,stroke:LC[l.k],'stroke-width':1}));
  s.append(el('rect',{x:W-pr+1,y:l.ty-8,width:pr-2,height:16,rx:3,fill:LC[l.k]}),el('text',{x:W-pr+5,y:l.ty+4,'font-size':10.5,fill:'var(--card)','font-weight':700},usd(l.v)),
   el('text',{x:pl+4,y:lab[k].ty,'font-size':11,'font-weight':600,fill:LC[l.k],stroke:'var(--card)','stroke-width':3,'paint-order':'stroke'},l.l))}
 for(const m of mk){const i=idx(m.t),cx=X(i),buy=m.k=='buy',cy=buy?Y(b[i][3])+12:Y(b[i][2])-12,d=buy?`M${cx} ${cy-7}L${cx+7} ${cy+5}L${cx-7} ${cy+5}Z`:`M${cx} ${cy+7}L${cx+7} ${cy-5}L${cx-7} ${cy-5}Z`;
  s.append(el('line',{x1:cx,x2:cx,y1:Y(m.p),y2:cy,stroke:buy?'var(--up)':'var(--dn)','stroke-width':1,opacity:.6}),el('path',{d,fill:buy?'var(--up)':'var(--dn)',stroke:'var(--card)','stroke-width':2,'stroke-linejoin':'round'}))}
 const L=b[n-1];s.append(el('line',{x1:pl,x2:W-pr,y1:Y(L[4]),y2:Y(L[4]),stroke:'var(--fg)','stroke-width':1,opacity:.35}),el('rect',{x:W-pr+1,y:Y(L[4])-8,width:pr-2,height:16,rx:3,fill:'var(--fg)'}),el('text',{x:W-pr+5,y:Y(L[4])+4,'font-size':10.5,fill:'var(--card)','font-weight':700},usd(L[4])));
 if(hv!=null){const i=Math.min(n-1,Math.max(0,Math.floor((hv-pl)/step))),[t,o,h,l,c,v]=b[i],cx=X(i);
  s.append(el('line',{x1:cx,x2:cx,y1:pt,y2:vt+vh,stroke:'var(--mut)','stroke-width':1,'stroke-dasharray':'3 3'}),el('line',{x1:pl,x2:W-pr,y1:Y(c),y2:Y(c),stroke:'var(--mut)','stroke-width':1,'stroke-dasharray':'3 3'}));
  const here=mk.filter(m=>idx(m.t)==i).map(m=>`<div class=${m.k=='buy'?'tu':'td'}>${m.k=='buy'?'▲ 매수':'▼ 매도'} ${m.q}주 @ ${usd(m.p)}${m.pnl!=null?' · '+(m.pnl>=0?'+':'')+won(m.pnl*D.fx):''}</div>`).join('');
  const chg=(c/o-1)*100;tip.innerHTML=`<b>${hm(t)}</b> <span class=${chg>=0?'tu':'td'}>${chg>=0?'+':''}${chg.toFixed(2)}%</span><br>시 ${usd(o)} · 고 ${usd(h)}<br>저 ${usd(l)} · 종 ${usd(c)}<br>거래량 ${(v||0).toLocaleString('ko-KR')}`+(vw[i]?`<br>VWAP ${usd(vw[i])}`:'')+here;
  tip.style.display='block';tip.style.left=Math.min(Math.max(cx-80,0),W-170)+'px'}else tip.style.display='none';
 box.append(s);msg.textContent=`${sym} 1분봉 ${n}개 · ${hm(b[0][0])}~${hm(L[0])} · 10초마다 갱신 · 현재 ${usd(L[4])}`+(D.note?' · '+D.note:'')}
const mv=e=>{const r=box.getBoundingClientRect();hv=(e.touches?e.touches[0].clientX:e.clientX)-r.left;draw()};
box.addEventListener('pointermove',mv);box.addEventListener('pointerdown',mv);box.addEventListener('pointerleave',()=>{hv=null;draw()});
const pick=(sel,f)=>document.querySelectorAll(sel).forEach(a=>a.addEventListener('click',()=>{document.querySelectorAll(sel).forEach(x=>x.classList.toggle('on',x==a));f(a);hv=null;load()}));
pick('button[data-sym]',a=>sym=a.dataset.sym);pick('button[data-span]',a=>{span=+a.dataset.span;try{localStorage.setItem('span',span)}catch(e){}});
document.querySelectorAll('button[data-span]').forEach(a=>a.classList.toggle('on',+a.dataset.span==span));
addEventListener('resize',draw);load();setInterval(load,10000)})();
"""
