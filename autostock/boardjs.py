"""차트 탭 스크립트: 캔버스 봉 차트(드래그 이동, 휠·두 손가락 확대축소, 두 번 눌러 원위치), 지지·저항·박스·추천 구간, 호가창."""
BOARD_JS = r"""
(()=>{const cv=document.getElementById('bc');if(!cv)return;const ctx=cv.getContext('2d');
const q=new URLSearchParams(location.search),K=q.get('k');let sym='SOXL',tf='5m',D=null,PLAN=null,end=0,n=90,follow=true,hov=null;
try{sym=localStorage.getItem('bsym')||sym;tf=localStorage.getItem('btf')||tf}catch(e){}
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const usd=v=>'$'+(v>=1000?v.toFixed(0):v.toFixed(2));
const kst=(t,d)=>new Date(t).toLocaleString('ko-KR',Object.assign({hour12:false,timeZone:'Asia/Seoul'},d?{month:'2-digit',day:'2-digit'}:{hour:'2-digit',minute:'2-digit'}));
const ymd=t=>new Date(t).toLocaleDateString('ko-KR',{year:'2-digit',month:'2-digit',day:'2-digit',timeZone:'Asia/Seoul'});
function mark(){document.querySelectorAll('[data-bsym]').forEach(b=>b.classList.toggle('on',b.dataset.bsym==sym));document.querySelectorAll('[data-btf]').forEach(b=>b.classList.toggle('on',b.dataset.btf==tf))}
async function load(reset){const msg=document.getElementById('bmsg');try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=board&sym=${sym}&tf=${tf}`);const nd=await r.json();
  if(nd.error&&!(nd.bars||[]).length){msg.textContent='차트를 불러오지 못했습니다: '+nd.error;return}
  const old=D,oldL=old?old.bars.length:0;D=nd;const L=D.bars.length,FH=D.fc?D.fc.h:0;
  if(reset||!old){n=Math.min(90+FH,L+FH);end=L+FH;follow=true}
  else if(follow){end=L+Math.max(0,end-oldL)}
  else{const t=old.bars[Math.max(0,Math.min(end,oldL)-1)][0];let i=D.bars.findIndex(b=>b[0]>t);end=i<0?L:i}
  const lt=D.bars[L-1][0];msg.textContent=`${sym} ${document.querySelector('[data-btf].on')?.textContent||tf} · 봉 ${L}개 · 마지막 ${new Date(lt).toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Seoul'})}${D.kis_bars?' (최근 '+D.kis_bars+'개는 한국투자증권 시세)':''} · 드래그=시간 이동 · 휠/두 손가락=확대축소 · 두 번 누르면 최신으로`;
  draw()}catch(e){msg.textContent='연결 실패'}}
async function plan(){const el=document.getElementById('bplan');const s0=sym,t0=tf;try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=board&what=plan&sym=${sym}&tf=${tf}`);const p=await r.json();if(s0!=sym||t0!=tf)return;PLAN=p;
 if(p.error){el.innerHTML=`<div class=note>계획을 세우지 못했습니다: ${p.error}</div>`;draw();return}
 const name={BUY:sym+' 매수',AVOID:sym+' 사지 않기 (하락 쪽'+(sym=='SOXL'?' · SOXS 고려':sym=='SOXS'?' · SOXL 고려':'')+')',WAIT:'관망 (기다리기)'}[p.action];
 const cls=p.action=='BUY'?'up':p.action=='AVOID'?'dn':'mut',mid=(p.entry_lo+p.entry_hi)/2,rr=Math.abs(p.target-mid)/Math.max(Math.abs(mid-p.stop),1e-9);
 el.innerHTML=`<div class='big2 ${cls}'>${name}</div><div class=sub>확신도 ${Math.round(p.confidence*100)}% · 보유 ${p.horizon} · ${p.src}${p.at?' · '+new Date(p.at*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Seoul'})+' 기준':''}</div>`+
  `<dl class=kv><dt>${p.action=='BUY'?'진입':'기다릴 가격대'}</dt><dd>${usd(p.entry_lo)} ~ ${usd(p.entry_hi)}</dd><dt>목표</dt><dd class=up>${usd(p.target)}</dd><dt>손절</dt><dd class=dn>${usd(p.stop)}</dd><dt>손익비</dt><dd>${rr.toFixed(1)} : 1</dd></dl>`+
  `<div class=note>${(p.reasons||[]).map(x=>'· '+x).join('<br>')}</div>`+(p.long_view?`<div class=note><b>장기</b>: ${p.long_view}</div>`:'')+(p.note?`<div class='note warnt'>${p.note}</div>`:'');draw()}catch(e){el.innerHTML='<div class=note>계획 연결 실패</div>'}}
function draw(){if(!D||!D.bars||!D.bars.length)return;const dpr=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
 const B=D.bars,L=B.length,FL=(D.fc&&D.fc.line)?D.fc.line.length:0;n=Math.max(15,Math.min(n,L+FL));
 end=Math.max(n,Math.min(end,L+FL,L+n-5));follow=end>=L;const s=B.slice(Math.max(0,end-n),Math.min(end,L));
 const F=Math.max(0,end-L),FCL=FL?D.fc.line.slice(0,F):[],FCB=FL?D.fc.band.slice(0,F):[];n=s.length+F;
 const pr=58,pb=20,ph=H*0.78-pb,vt=H*0.80,vh=H*0.2-pb,pw=W-pr,bw=pw/n;
 const PP=(PLAN&&!PLAN.error)?[PLAN.target,PLAN.stop,PLAN.entry_lo,PLAN.entry_hi]:[];
 let lo=Math.min(...s.map(b=>b[3]),...FCL,...FCB.map(q=>q[0]),...PP),hi=Math.max(...s.map(b=>b[2]),...FCL,...FCB.map(q=>q[1]),...PP);const pad=(hi-lo)*0.08||lo*0.01;lo-=pad;hi+=pad;
 const Y=v=>4+(hi-v)/(hi-lo)*(ph-4),X=i=>(i+.5)*bw;const up=css('--up'),dn=css('--dn'),mut=css('--mut'),line=css('--line'),fg=css('--fg'),ok=css('--ok'),warn=css('--warn'),card=css('--card');
 ctx.font='11px system-ui';ctx.lineWidth=1;
 for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4,y=Y(v);ctx.strokeStyle=line;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(pw,y);ctx.stroke();ctx.fillStyle=mut;ctx.fillText(usd(v),pw+4,y+4)}
 const tIdx=t=>{let i=s.findIndex(b=>b[0]>=t);return i<0?(t>s[s.length-1][0]?s.length:-1):i};
 const P=PLAN&&!PLAN.error?PLAN:null;
 if(P){const col=P.action=='BUY'?ok:P.action=='AVOID'?css('--dn'):mut;
  if(P.entry_hi>=lo&&P.entry_lo<=hi){const y1=Y(Math.min(P.entry_hi,hi)),y2=Y(Math.max(P.entry_lo,lo));ctx.fillStyle=col;ctx.globalAlpha=.16;ctx.fillRect(0,y1,pw,Math.max(y2-y1,2));ctx.globalAlpha=.8;ctx.strokeStyle=col;ctx.strokeRect(0,y1,pw,Math.max(y2-y1,2));ctx.globalAlpha=1;
   ctx.fillStyle=col;ctx.font='bold 11px system-ui';ctx.fillText((P.action=='BUY'?'진입 ':P.action=='AVOID'?'회피 ':'대기 ')+usd(P.entry_lo)+'~'+usd(P.entry_hi),4,y2+12);ctx.font='11px system-ui'}
  for(const [v,c,t] of [[P.target,up,'목표'],[P.stop,dn,'손절']]){if(v<lo||v>hi)continue;ctx.strokeStyle=c;ctx.setLineDash([6,4]);ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(0,Y(v));ctx.lineTo(pw,Y(v));ctx.stroke();ctx.setLineDash([]);ctx.lineWidth=1;
   ctx.fillStyle=c;ctx.font='bold 11px system-ui';ctx.fillText(t+' '+usd(v),4,Y(v)-4);ctx.font='11px system-ui'}}
 const vmax=Math.max(...s.map(b=>b[5]||0))||1;
 for(let i=0;i<s.length;i++){const [t,o,h,l,c,v]=s[i],col=c>=o?up:dn,x=X(i);ctx.strokeStyle=col;ctx.fillStyle=col;
  ctx.beginPath();ctx.moveTo(x,Y(h));ctx.lineTo(x,Y(l));ctx.stroke();const w=Math.max(bw*.65,1);ctx.fillRect(x-w/2,Math.min(Y(o),Y(c)),w,Math.max(Math.abs(Y(o)-Y(c)),1));
  ctx.globalAlpha=.35;const vv=(v||0)/vmax*vh;ctx.fillRect(x-w/2,vt+vh-vv,w,vv);ctx.globalAlpha=1}
 const lab=(v,txt,col)=>{if(v<lo||v>hi)return;const y=Y(v);ctx.fillStyle=col;ctx.fillRect(pw+1,y-8,pr-2,16);ctx.fillStyle=card;ctx.font='bold 10.5px system-ui';ctx.fillText(txt,pw+4,y+4);ctx.font='11px system-ui'};
 if(P){lab(P.target,usd(P.target),up);lab(P.stop,usd(P.stop),dn)}
 const R=s.length;
 if(F&&R){const x0=X(R-1),c0=s[R-1][4],col=css('--vwap');
  ctx.beginPath();ctx.moveTo(x0,Y(c0));FCB.forEach((q,j)=>ctx.lineTo(X(R+j),Y(q[1])));for(let j=FCB.length-1;j>=0;j--)ctx.lineTo(X(R+j),Y(FCB[j][0]));ctx.closePath();
  ctx.fillStyle=col;ctx.globalAlpha=.1;ctx.fill();ctx.globalAlpha=1;
  const st=D.fc.strength||0;ctx.strokeStyle=col;ctx.lineWidth=1.2+2.8*st;ctx.globalAlpha=.3+.7*st;if(!st)ctx.setLineDash([4,3]);
  ctx.beginPath();ctx.moveTo(x0,Y(c0));FCL.forEach((v,j)=>ctx.lineTo(X(R+j),Y(v)));ctx.stroke();ctx.lineWidth=1;ctx.globalAlpha=1;ctx.setLineDash([]);
  ctx.strokeStyle=line;ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(x0+bw/2,0);ctx.lineTo(x0+bw/2,H-pb);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle=col;ctx.font='bold 11px system-ui';ctx.fillText(D.fc.model=='flat'?'예상: 방향 없음':'예상 (적중 '+Math.round(D.fc.dir_check)+'%) →',x0+bw,12);ctx.font='11px system-ui';lab(FCL[F-1],usd(FCL[F-1]),col)}
 const lc=s[R-1][4];ctx.strokeStyle=fg;ctx.globalAlpha=.4;ctx.beginPath();ctx.moveTo(0,Y(lc));ctx.lineTo(pw,Y(lc));ctx.stroke();ctx.globalAlpha=1;lab(lc,usd(lc),fg);
 ctx.fillStyle=mut;const day=tf=='1d'||tf=='1h';for(const i of [0,Math.floor((R-1)/2),R-1]){const t=s[i][0];const txt=day?kst(t,1):kst(t);const tw=ctx.measureText(txt).width;ctx.fillText(txt,Math.min(Math.max(X(i)-tw/2,0),pw-tw),H-5)}
 if(hov!=null&&hov>=0&&hov<pw&&Math.floor(hov/bw)<R){const i=Math.floor(hov/bw),b=s[i];ctx.strokeStyle=mut;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(X(i),0);ctx.lineTo(X(i),H-pb);ctx.stroke();ctx.setLineDash([]);
  const txt=`${day?kst(b[0],1)+' ':''}${kst(b[0])} 시${usd(b[1])} 고${usd(b[2])} 저${usd(b[3])} 종${usd(b[4])}`;ctx.font='11px system-ui';const tw=ctx.measureText(txt).width+10;
  ctx.fillStyle=fg;ctx.fillRect(Math.min(Math.max(X(i)-tw/2,0),pw-tw),0,tw,17);ctx.fillStyle=card;ctx.fillText(txt,Math.min(Math.max(X(i)-tw/2,0),pw-tw)+5,12)}}
// 조작: 드래그 이동, 휠·두 손가락 확대축소, 두 번 눌러 최신으로
const P=new Map();let drag=null,pinch=null,lastTap=0;
cv.addEventListener('pointerdown',e=>{cv.setPointerCapture(e.pointerId);P.set(e.pointerId,e.clientX);
 if(P.size==1){drag={x:e.clientX,end};const now=Date.now();if(now-lastTap<300&&D){const FH=D.fc?D.fc.h:0;end=D.bars.length+FH;n=90+FH;draw()}lastTap=now}
 if(P.size==2){const xs=[...P.values()];pinch={d:Math.abs(xs[0]-xs[1])||1,n,end};drag=null}});
cv.addEventListener('pointermove',e=>{const r=cv.getBoundingClientRect();if(!P.has(e.pointerId)){if(e.pointerType=='mouse'){hov=e.clientX-r.left;draw()}return}
 P.set(e.pointerId,e.clientX);if(!D)return;const bw=(cv.clientWidth-58)/n;
 if(pinch&&P.size==2){const xs=[...P.values()],d=Math.abs(xs[0]-xs[1])||1;const nn=Math.round(pinch.n*pinch.d/d);const right=pinch.end;n=Math.max(15,Math.min(nn,D.bars.length));end=right;draw()}
 else if(drag){end=Math.round(drag.end-(e.clientX-drag.x)/bw);draw()}});
const up_=e=>{P.delete(e.pointerId);if(P.size<2)pinch=null;if(!P.size)drag=null};cv.addEventListener('pointerup',up_);cv.addEventListener('pointercancel',up_);
cv.addEventListener('pointerleave',()=>{hov=null;draw()});
cv.addEventListener('wheel',e=>{e.preventDefault();if(!D)return;const r=cv.getBoundingClientRect(),bw=(cv.clientWidth-58)/n,fx=Math.min(Math.max((e.clientX-r.left)/(cv.clientWidth-58),0),1);
 const at=end-n+fx*n,nn=Math.round(n*(e.deltaY>0?1.15:1/1.15));n=Math.max(15,Math.min(nn,D.bars.length));end=Math.round(at+(1-fx)*n);draw()},{passive:false});
document.querySelectorAll('[data-bzoom]').forEach(b=>b.addEventListener('click',()=>{n=Math.round(n*(b.dataset.bzoom=='in'?0.7:1.4));draw()}));
document.querySelectorAll('[data-bsym]').forEach(b=>b.addEventListener('click',()=>{sym=b.dataset.bsym;try{localStorage.setItem('bsym',sym)}catch(e){}mark();PLAN=null;load(true);plan()}));
document.querySelectorAll('[data-btf]').forEach(b=>b.addEventListener('click',()=>{tf=b.dataset.btf;try{localStorage.setItem('btf',tf)}catch(e){}mark();PLAN=null;load(true);plan()}));
addEventListener('resize',draw);mark();load(true);plan();setInterval(()=>load(false),10000);setInterval(plan,120000)})();
"""
