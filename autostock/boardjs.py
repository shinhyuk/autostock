"""차트 탭 스크립트: 캔버스 봉 차트(드래그 이동, 휠·두 손가락 확대축소, 두 번 눌러 원위치), 지지·저항·박스·추천 구간, 호가창."""
BOARD_JS = r"""
(()=>{const cv=document.getElementById('bc');if(!cv)return;const ctx=cv.getContext('2d');
const q=new URLSearchParams(location.search),K=q.get('k');let sym='SOXL',tf='5m',D=null,end=0,n=90,follow=true,hov=null;
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
  info();draw()}catch(e){msg.textContent='연결 실패'}}
function info(){const el=document.getElementById('binfo');if(!D||!D.last){el.innerHTML='';return}
 const st=D.stats||{},p=(a)=>a&&a[0]+a[1]?Math.round(a[0]/(a[0]+a[1])*100)+'% ('+(a[0]+a[1])+'번)':'자료 부족';
 let h=`<div class=sub>현재 ${usd(D.last)} · 한 봉 평균 움직임(ATR) ${usd(D.atr)}</div><dl class=kv>`;
 h+=`<dt><span class=lgs></span>저항대 (위)</dt><dd>${D.res?usd(D.res.lo)+' ~ '+usd(D.res.hi)+' ('+D.res.n+'번 닿음)':'-'}</dd>`;
 h+=`<dt><span class=lgr></span>지지대 (아래)</dt><dd>${D.sup?usd(D.sup.lo)+' ~ '+usd(D.sup.hi)+' ('+D.sup.n+'번 닿음)':'-'}</dd>`;
 h+=`<dt><span class=lgb></span>박스</dt><dd>${D.box?usd(D.box.lo)+' ~ '+usd(D.box.hi):'없음 (위·아래에 2번씩 닿는 옆걸음 구간이 아님)'}</dd></dl>`;
 for(const z of D.zones||[]){const buy=z.k=='buy';
  h+=`<div class='zone ${buy?'zb':'zs'}'><b>${buy?'추천 매수 구간 (지지선 위)':'추천 매도·하락 구간 (저항선 아래)'}</b> ${usd(z.lo)} ~ ${usd(z.hi)}<br>`+
   `${buy?'목표 '+usd(z.target)+' · 손절 '+usd(z.stop):'목표(아래) '+usd(z.target)+' · 손절(위) '+usd(z.stop)} · 손익비 ${z.rr.toFixed(1)} : 1</div>`}
 const fc=D.fc;if(fc&&fc.line&&fc.line.length){const e=fc.line[fc.h-1],c=fc.check||{};
  h+=`<div class='zone' style='border-left:4px solid var(--vwap);background:color-mix(in srgb,var(--vwap) 10%,transparent)'><b>예상선 (${fc.label})</b> ${fc.h}봉 뒤 ${usd(e)} (${((e/D.last-1)*100).toFixed(1)}%) · 차트를 왼쪽으로 끌면 ${fc.line.length}봉 뒤까지 (검증한 ${fc.h}봉 뒤부터는 기울기 없이 범위만 넓어짐)<br>`+
   `<span class=note>${fc.model=='flat'?'과거에 "흐름 이어짐"·"되돌림" 둘 다 방향을 55% 넘게 맞히지 못해 평평하게 그렸습니다. ':`<b>방향 검증</b>: 고를 때 안 본 최근 구간에서 ${fc.h}봉 뒤 방향을 맞힌 비율 <b>${fc.dir_check!=null?Math.round(fc.dir_check):'-'}%</b> (50%면 동전 던지기). `}`+
   `옅은 띠는 50% 가능성 범위(검증: 실제로 그 안에 든 비율 ${c.cov50!=null?Math.round(c.cov50):'-'}%).</span></div>`}
 h+=`<div class=note>이 차트의 과거 기록: 지지선 근처에 왔을 때 위로 1 ATR 먼저 간 비율 <b>${p(st.sup)}</b> · 저항선 근처에서 아래로 먼저 간 비율 <b>${p(st.res)}</b>. 50% 근처면 선만 보고 방향을 정하기 어렵다는 뜻입니다.</div>`;
 el.innerHTML=h}
function draw(){if(!D||!D.bars||!D.bars.length)return;const dpr=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
 const B=D.bars,L=B.length,FL=(D.fc&&D.fc.line)?D.fc.line.length:0;n=Math.max(15,Math.min(n,L+FL));
 end=Math.max(n,Math.min(end,L+FL,L+n-5));follow=end>=L;const s=B.slice(Math.max(0,end-n),Math.min(end,L));
 const F=Math.max(0,end-L),FCL=FL?D.fc.line.slice(0,F):[],FCB=FL?D.fc.band.slice(0,F):[];n=s.length+F;
 const pr=58,pb=20,ph=H*0.78-pb,vt=H*0.80,vh=H*0.2-pb,pw=W-pr,bw=pw/n;
 let lo=Math.min(...s.map(b=>b[3]),...FCL,...FCB.map(q=>q[0])),hi=Math.max(...s.map(b=>b[2]),...FCL,...FCB.map(q=>q[1]));const pad=(hi-lo)*0.08||lo*0.01;lo-=pad;hi+=pad;
 const Y=v=>4+(hi-v)/(hi-lo)*(ph-4),X=i=>(i+.5)*bw;const up=css('--up'),dn=css('--dn'),mut=css('--mut'),line=css('--line'),fg=css('--fg'),ok=css('--ok'),warn=css('--warn'),card=css('--card');
 ctx.font='11px system-ui';ctx.lineWidth=1;
 for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4,y=Y(v);ctx.strokeStyle=line;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(pw,y);ctx.stroke();ctx.fillStyle=mut;ctx.fillText(usd(v),pw+4,y+4)}
 const tIdx=t=>{let i=s.findIndex(b=>b[0]>=t);return i<0?(t>s[s.length-1][0]?s.length:-1):i};
 for(const z of D.zones||[]){if(z.hi<lo||z.lo>hi)continue;ctx.fillStyle=z.k=='buy'?ok:warn;ctx.globalAlpha=.13;ctx.fillRect(0,Y(z.hi),pw,Math.max(Y(z.lo)-Y(z.hi),2));ctx.globalAlpha=1}
 if(D.box){const i0=Math.max(0,tIdx(D.box.start));if(i0<n&&D.box.hi>lo&&D.box.lo<hi){ctx.strokeStyle=warn;ctx.setLineDash([4,3]);ctx.strokeRect(i0*bw,Y(D.box.hi),pw-i0*bw,Y(D.box.lo)-Y(D.box.hi));ctx.setLineDash([]);ctx.fillStyle=warn;ctx.fillText('박스',i0*bw+3,Y(D.box.hi)-3)}}
 for(const lv of D.levels||[]){const a=lv.lo??lv.v,b=lv.hi??lv.v;if(b<lo||a>hi)continue;const isS=lv.v<D.last,col=isS?ok:warn,main=(D.sup&&lv.v==D.sup.v)||(D.res&&lv.v==D.res.v);
  const y1=Y(Math.min(b,hi)),y2=Y(Math.max(a,lo));ctx.fillStyle=col;ctx.globalAlpha=main?.22:.1;ctx.fillRect(0,y1,pw,Math.max(y2-y1,2));ctx.globalAlpha=main?.9:.45;ctx.strokeStyle=col;ctx.strokeRect(0,y1,pw,Math.max(y2-y1,2));ctx.globalAlpha=1;
  if(main){ctx.fillStyle=col;ctx.font='bold 11px system-ui';ctx.fillText((isS?'지지대 ':'저항대 ')+usd(a)+'~'+usd(b),4,isS?y2+12:y1-4);ctx.font='11px system-ui'}}
 const vmax=Math.max(...s.map(b=>b[5]||0))||1;
 for(let i=0;i<s.length;i++){const [t,o,h,l,c,v]=s[i],col=c>=o?up:dn,x=X(i);ctx.strokeStyle=col;ctx.fillStyle=col;
  ctx.beginPath();ctx.moveTo(x,Y(h));ctx.lineTo(x,Y(l));ctx.stroke();const w=Math.max(bw*.65,1);ctx.fillRect(x-w/2,Math.min(Y(o),Y(c)),w,Math.max(Math.abs(Y(o)-Y(c)),1));
  ctx.globalAlpha=.35;const vv=(v||0)/vmax*vh;ctx.fillRect(x-w/2,vt+vh-vv,w,vv);ctx.globalAlpha=1}
 const lab=(v,txt,col)=>{if(v<lo||v>hi)return;const y=Y(v);ctx.fillStyle=col;ctx.fillRect(pw+1,y-8,pr-2,16);ctx.fillStyle=card;ctx.font='bold 10.5px system-ui';ctx.fillText(txt,pw+4,y+4);ctx.font='11px system-ui'};
 if(D.res)lab(D.res.v,usd(D.res.v),warn);if(D.sup)lab(D.sup.v,usd(D.sup.v),ok);
 const R=s.length;
 if(F&&R){const x0=X(R-1),c0=s[R-1][4],col=css('--vwap');
  ctx.beginPath();ctx.moveTo(x0,Y(c0));FCB.forEach((q,j)=>ctx.lineTo(X(R+j),Y(q[1])));for(let j=FCB.length-1;j>=0;j--)ctx.lineTo(X(R+j),Y(FCB[j][0]));ctx.closePath();
  ctx.fillStyle=col;ctx.globalAlpha=.1;ctx.fill();ctx.globalAlpha=1;
  ctx.strokeStyle=col;ctx.lineWidth=2.2;ctx.beginPath();ctx.moveTo(x0,Y(c0));FCL.forEach((v,j)=>ctx.lineTo(X(R+j),Y(v)));ctx.stroke();ctx.lineWidth=1;
  ctx.strokeStyle=line;ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(x0+bw/2,0);ctx.lineTo(x0+bw/2,H-pb);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle=col;ctx.font='bold 11px system-ui';ctx.fillText('예상 →',x0+bw,12);ctx.font='11px system-ui';lab(FCL[F-1],usd(FCL[F-1]),col)}
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
document.querySelectorAll('[data-bsym]').forEach(b=>b.addEventListener('click',()=>{sym=b.dataset.bsym;try{localStorage.setItem('bsym',sym)}catch(e){}mark();load(true);book();longv()}));
document.querySelectorAll('[data-btf]').forEach(b=>b.addEventListener('click',()=>{tf=b.dataset.btf;try{localStorage.setItem('btf',tf)}catch(e){}mark();load(true)}));
async function book(){const el=document.getElementById('bbook');try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=board&what=book&sym=${sym}`);const d=await r.json();
 if(d.error||!((d.asks||[]).length||(d.bids||[]).length)){el.innerHTML=`<div class=note>호가를 받지 못했습니다${d.error?': '+d.error:''} (장이 닫혔거나 증권사가 이 시간대 호가를 주지 않음)</div>`;return}
 const mx=Math.max(...[...d.asks,...d.bids].map(x=>x[1]||0),1);const row=(x,cls)=>`<div class='brow ${cls}'><i style='width:${(x[1]||0)/mx*100}%'></i><span>${usd(x[0])}</span><span>${(x[1]||0).toLocaleString('ko-KR')}</span></div>`;
 const sp=d.asks.length&&d.bids.length?((d.asks[0][0]/d.bids[0][0]-1)*100).toFixed(2)+'%':'-';
 el.innerHTML=`<div class=bhead><span>가격</span><span>잔량</span></div>`+[...d.asks].reverse().map(x=>row(x,'ask')).join('')+`<div class=bmid>호가 차이 ${sp}${d.last?' · 현재가 '+usd(d.last):''}</div>`+d.bids.map(x=>row(x,'bid')).join('')+
  `<div class=note>${d.asks.length<=1?'미국 주식은 계좌 권한에 따라 1호가만 제공될 수 있습니다 · ':''}3초마다 갱신</div>`}catch(e){el.innerHTML='<div class=note>호가 연결 실패</div>'}}
async function longv(){const el=document.getElementById('blong');try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=board&what=long&sym=${sym}`);const d=await r.json();
 if(d.error){el.innerHTML=`<div class=note>장기 자료를 불러오지 못했습니다: ${d.error}</div>`;return}
 const pc=v=>v==null?'-':(v>=0?'+':'')+v.toFixed(0)+'%',tr=d.above200?'<b class=up>200일 평균 위 (장기 상승 추세)</b>':'<b class=dn>200일 평균 아래 (장기 하락 추세)</b>';
 let h=`<div class=sub>${sym} ${usd(d.last)} · 50일 평균 ${usd(d.ma50)} · 200일 평균 ${usd(d.ma200)}</div><div style='margin:6px 0'>${tr}</div>`+
 `<dl class=kv><dt>1년 고점 / 저점</dt><dd>${usd(d.hi252)} / ${usd(d.lo252)}</dd><dt>1년 고점 대비</dt><dd class=${d.dd<0?'dn':'up'}>${d.dd.toFixed(1)}% (${d.bucket})</dd>`+
 `<dt><span class=lgs></span>주봉 저항대</dt><dd>${d.wres?usd(d.wres.lo)+' ~ '+usd(d.wres.hi):'-'}</dd><dt><span class=lgr></span>주봉 지지대</dt><dd>${d.wsup?usd(d.wsup.lo)+' ~ '+usd(d.wsup.hi):'-'}</dd></dl>`;
 const f=d.fwd,eps=(d.episodes||[]).filter(e=>e[1]<Date.now()-30*864e5);
 h+=`<h3>지금과 비슷했던 날(고점 대비 ${d.bucket}, ${d.above200?'200일 위':'200일 아래'})의 그 뒤 수익률 · 최근 5년</h3><table><tr><th>기간</th><th class=r>중간값</th><th class=r>오른 비율</th><th class=r>하위10%~상위10%</th><th class=r>일수</th></tr>`+
  [[21,'1개월'],[63,'3개월'],[126,'6개월']].map(([k,l])=>{const x=f[k];return `<tr><td>${l}</td><td class=r>${pc(x.med)}</td><td class=r>${x.up==null?'-':x.up.toFixed(0)+'%'}</td><td class=r>${x.p10==null?'-':pc(x.p10)+' ~ '+pc(x.p90)}</td><td class=r>${x.n}</td></tr>`}).join('')+`</table>`;
 h+=`<div class=note>비슷했던 시기: ${(d.episodes||[]).map(e=>ymd(e[0])+'~'+ymd(e[1])).join(' · ')||'-'} → 실제로는 <b>${eps.length}번의 사례</b>뿐이라 참고만 하세요.</div>`;
 if(d.decay){const want=d.decay.soxx*d.decay.mult;h+=`<h3>레버리지 감가 (최근 1년)</h3><div class=note>SOXX(반도체 지수) ${pc(d.decay.soxx)} → ${d.decay.mult>0?'3배':'-3배'}면 ${pc(want)} 이어야 하지만 실제 ${sym} 은 <b>${pc(d.decay.etf)}</b>. 3배 상품은 출렁일수록 매일 손실이 쌓여 오래 들고 있으면 지수의 3배보다 훨씬 못합니다. 장기 보유라면 ${sym=='SOXS'?'인버스 장기 보유는 특히 불리하고, ':''}SOXX 같은 1배 상품이 맞습니다.</div>`}
 el.innerHTML=h}catch(e){el.innerHTML='<div class=note>장기 자료 연결 실패</div>'}}
addEventListener('resize',draw);mark();load(true);book();longv();setInterval(()=>load(false),10000);setInterval(book,3000)})();
"""
