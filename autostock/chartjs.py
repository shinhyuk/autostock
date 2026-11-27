"""모든 탭이 같이 쓰는 캔버스 차트: 봉·거래량·VWAP·매매 표시·가로선·구간 띠, 예상선(미래 시간축 포함)과 지난 예측들,
드래그로 시간 이동, 휠·두 손가락·버튼으로 확대축소, 두 번 누르면 최신으로."""
CHART_CORE = r"""
window.MakeChart=function(cv,opt){opt=opt||{};const ctx=cv.getContext('2d');let D=null,end=0,n=90,hov=null,tapI=null,FD=0;
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const usd=v=>v==null?'-':'$'+(Math.abs(v)>=1000?v.toFixed(0):v.toFixed(2));
const fmt=(t,withDay)=>new Date(t).toLocaleString('ko-KR',Object.assign({hour12:false,timeZone:'Asia/Seoul'},withDay?{month:'2-digit',day:'2-digit'}:{hour:'2-digit',minute:'2-digit'}));
const LC=()=>({entry:css('--mut'),stop:css('--dn'),take:css('--up'),trail:css('--warn'),rng:css('--warn'),box:css('--mut'),bxl:css('--up'),bxs:css('--dn'),noise:css('--noise'),plan:css('--ok'),wait:css('--mut')});
function stepMs(){const b=D.bars;if(b.length<3)return 60000;const d=[];for(let i=Math.max(1,b.length-50);i<b.length;i++)d.push(b[i][0]-b[i-1][0]);d.sort((x,y)=>x-y);return d[d.length>>1]||60000}
function futLen(){if(!D||!D.fc)return 0;const f=D.fc;if(f.pts&&f.pts.length&&D.bars.length>2){const L=D.bars.length;return Math.min(1500,Math.max(0,Math.ceil((f.pts[f.pts.length-1][0]-D.bars[L-1][0])/stepMs())))}return f.line?f.line.length:0}
function set(nd,reset,initN){const old=D,oldL=old?old.bars.length:0,wasFollow=!old||end>=oldL;D=nd;const L=D.bars.length;FD=D.fc?Math.min(D.fc.h||0,futLen()):0;
 if(reset||!old){n=Math.min(initN||opt.initN||90,L)+FD;end=L+FD}
 else if(wasFollow){end=L+Math.max(0,end-oldL)}
 else{const t=old.bars[Math.max(0,Math.min(end,oldL)-1)][0];let i=D.bars.findIndex(b=>b[0]>t);end=i<0?L:i}
 draw()}
function draw(){if(!D||!D.bars||D.bars.length<2){ctx.clearRect(0,0,cv.width,cv.height);return}
 const dpr=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
 const B=D.bars,L=B.length,FL=futLen(),SM=stepMs(),lastT=B[L-1][0];
 n=Math.max(15,Math.min(n,L+FL));end=Math.max(Math.min(n,L),Math.min(end,L+FL,L+n-5));const c0=end-n;
 const pr=60,pb=22,ph=H*0.8-pb,vt=H*0.82,vh=H*0.18-pb,pw=W-pr,bw=pw/n,X=c=>(c-c0+.5)*bw;
 const tOf=c=>c<L?B[Math.max(0,c)][0]:lastT+(c-L+1)*SM;
 const colOf=t=>{if(t>lastT)return L-1+(t-lastT)/SM;let a=0,z=L-1;while(a<z){const m=(a+z+1)>>1;if(B[m][0]<=t)a=m;else z=m-1}return a};
 const vis=[];for(let c=Math.max(0,c0);c<Math.min(end,L);c++)vis.push(c);
 const fc=D.fc,fT=c=>fc.t+c*fc.step;
 const fall=fc?(fc.pts&&fc.pts.length?fc.pts.slice(1).map(([t,v,a,b])=>[colOf(t),v,[a,b]]):fc.line.map((v,k)=>[colOf(fT(k+1)),v,fc.band[k]])):[];
 const fs=fc&&fc.pts&&fc.pts.length?[colOf(fc.pts[0][0]),fc.pts[0][1]]:fc?[colOf(fc.t),fc.p0]:null;
 const fpts=fall.filter(p=>p[0]>=c0-1&&p[0]<=end+1);
 const rngV=[];for(const c of vis){rngV.push(B[c][2],B[c][3])}for(const p of fpts){rngV.push(p[1],p[2][0],p[2][1])}
 const plan=D.plan;if(plan)rngV.push(...[plan.target,plan.stop,plan.entry_lo,plan.entry_hi].filter(v=>v!=null));
 let lo=Math.min(...rngV),hi=Math.max(...rngV);const pad=(hi-lo)*.07||lo*.01;lo-=pad;hi+=pad;const Y=v=>6+(hi-v)/(hi-lo)*(ph-6);
 const up=css('--up'),dn=css('--dn'),mut=css('--mut'),line=css('--line'),fg=css('--fg'),card=css('--card'),vw=css('--vwap'),ok=css('--ok'),warn=css('--warn'),lc=LC();
 ctx.font='11px system-ui';ctx.lineWidth=1;
 for(let k=0;k<=4;k++){const y=6+(ph-6)*k/4;ctx.strokeStyle=line;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(pw,y);ctx.stroke();ctx.fillStyle=mut;ctx.fillText(usd(hi-(hi-lo)*k/4),pw+5,y+4)}
 // 구간 띠·범위
 const fromC=t=>t?Math.max(c0,Math.ceil(colOf(t))):c0;
 if(D.range&&D.range.length==2){const x=Math.max(0,X(fromC(D.range_t))-bw/2);ctx.fillStyle=warn;ctx.globalAlpha=.07;ctx.fillRect(x,Y(D.range[1]),pw-x,Y(D.range[0])-Y(D.range[1]));ctx.globalAlpha=1}
 for(const z of D.bands||[]){const x=Math.max(0,X(fromC(D.range_t))-bw/2),col=z.k=='bl'?up:z.k=='bs'?dn:z.k=='buy'?ok:z.k=='avoid'?dn:mut;ctx.fillStyle=col;ctx.globalAlpha=.13;ctx.fillRect(x,Y(z.hi),pw-x,Math.max(Y(z.lo)-Y(z.hi),2));ctx.globalAlpha=1;
  if(z.l){ctx.fillStyle=col;ctx.font='bold 11px system-ui';ctx.fillText(z.l,x+4,Y(z.lo)+12);ctx.font='11px system-ui'}}
 // 거래량·봉
 const vmax=Math.max(...vis.map(c=>B[c][5]||0))||1,w=Math.max(bw*.62,1);
 for(const c of vis){const [t,o,h,l,cl,v]=B[c],col=cl>=o?up:dn,x=X(c);ctx.fillStyle=col;ctx.globalAlpha=.3;const vv=(v||0)/vmax*vh;ctx.fillRect(x-w/2,vt+vh-vv,w,vv);ctx.globalAlpha=1;
  ctx.strokeStyle=col;ctx.beginPath();ctx.moveTo(x,Y(h));ctx.lineTo(x,Y(l));ctx.stroke();if(bw>=2.5)ctx.fillRect(x-w/2,Math.min(Y(o),Y(cl)),w,Math.max(Math.abs(Y(o)-Y(cl)),1))}
 if(D.vwap){ctx.strokeStyle=vw;ctx.lineWidth=1.5;ctx.beginPath();let st=false;for(const c of vis){const v=D.vwap[c];if(v==null){st=false;continue}if(!st){ctx.moveTo(X(c),Y(v));st=true}else ctx.lineTo(X(c),Y(v))}ctx.stroke();ctx.lineWidth=1}
 // 지난 예측들: 맞음 초록, 틀림 주황, 진행 중 회색
 for(const p of D.fc&&D.fc.past||[]){const xs=p.pts.map(([k,v])=>[colOf(p.t+k*p.step),v]);
  const x0=colOf(p.t);if(x0>end||xs[xs.length-1][0]<c0)continue;ctx.strokeStyle=p.hit==null?mut:p.hit?ok:warn;ctx.globalAlpha=.5;ctx.lineWidth=1.2;
  ctx.beginPath();ctx.moveTo(X(x0),Y(p.p0));for(const [c,v] of xs)ctx.lineTo(X(c),Y(v));ctx.stroke();ctx.globalAlpha=1;ctx.lineWidth=1}
 // 예상선: 세기만큼 진하게
 if(fpts.length){const st=fc.strength||0,x0=fs[0];ctx.fillStyle=vw;ctx.globalAlpha=.06+.1*st;ctx.beginPath();ctx.moveTo(X(x0),Y(fs[1]));fpts.forEach(p=>ctx.lineTo(X(p[0]),Y(p[2][1])));
  for(let k=fpts.length-1;k>=0;k--)ctx.lineTo(X(fpts[k][0]),Y(fpts[k][2][0]));ctx.closePath();ctx.fill();ctx.globalAlpha=.35+.65*st;ctx.strokeStyle=vw;ctx.lineWidth=1.4+2.6*st;if(!st)ctx.setLineDash([5,3]);
  ctx.beginPath();ctx.moveTo(X(x0),Y(fs[1]));fpts.forEach(p=>ctx.lineTo(X(p[0]),Y(p[1])));ctx.stroke();ctx.setLineDash([]);ctx.lineWidth=1;ctx.globalAlpha=1;
  const nowX=X(L-1)+bw/2;if(nowX<pw){ctx.strokeStyle=line;ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(nowX,0);ctx.lineTo(nowX,H-pb);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle=vw;ctx.font='bold 11px system-ui';
   ctx.fillText((fc.model=='flat'?'예상: 방향 없음':'예상')+(fc.acc&&fc.acc.dir!=null&&fc.model!='flat'?' · 적중 '+Math.round(fc.acc.dir)+'%':''),nowX+4,14);ctx.font='11px system-ui'}}
 // 가로선 (이름은 왼쪽, 가격표는 오른쪽 · 겹치면 비켜 그림)
 const tags=[];for(const ln of D.lines||[]){if(ln.v<lo||ln.v>hi)continue;const col=lc[ln.k]||mut,y=Y(ln.v);ctx.strokeStyle=col;ctx.lineWidth=1.4;ctx.setLineDash(ln.k=='entry'?[2,3]:['box','bxl','bxs'].includes(ln.k)?[2,4]:[6,4]);
  ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(pw,y);ctx.stroke();ctx.setLineDash([]);ctx.lineWidth=1;ctx.fillStyle=col;ctx.font='bold 11px system-ui';ctx.strokeStyle=card;ctx.lineWidth=3;ctx.strokeText(ln.l,4,y-4);ctx.fillText(ln.l,4,y-4);ctx.lineWidth=1;ctx.font='11px system-ui';tags.push([y,usd(ln.v),col])}
 const lastC=Math.min(end,L)-1;if(lastC>=0)tags.push([Y(B[lastC][4]),usd(B[lastC][4]),fg,1]);if(fpts.length){const e=fpts[fpts.length-1];tags.push([Y(e[1]),usd(e[1]),vw])}
 tags.sort((a,b)=>a[0]-b[0]);let prev=-1e9;for(const t of tags){t[4]=Math.max(t[0],prev+16);prev=t[4]}
 for(const [y,txt,col,isLast,ty] of tags){ctx.fillStyle=col;ctx.fillRect(pw+1,ty-8,pr-2,16);ctx.fillStyle=card;ctx.font='bold 10.5px system-ui';ctx.fillText(txt,pw+5,ty+4);ctx.font='11px system-ui'}
 // 매매 표시
 for(const m of D.marks||[]){const c=Math.round(colOf(m.t));if(c<c0||c>=end)continue;const x=X(c),buy=m.k=='buy',y=buy?Y(B[c][3])+12:Y(B[c][2])-12;ctx.fillStyle=buy?up:dn;ctx.beginPath();
  if(buy){ctx.moveTo(x,y-7);ctx.lineTo(x+7,y+5);ctx.lineTo(x-7,y+5)}else{ctx.moveTo(x,y+7);ctx.lineTo(x+7,y-5);ctx.lineTo(x-7,y-5)}ctx.closePath();ctx.fill()}
 // 시간축 (미래 포함)
 ctx.fillStyle=mut;const span=tOf(end-1)-tOf(c0),day=span>36*3600e3;for(let k=0;k<5;k++){const c=Math.round(c0+(n-1)*k/4),t=tOf(c),txt=day?fmt(t,1):fmt(t);const tw=ctx.measureText(txt).width;ctx.fillStyle=c>=L?vw:mut;ctx.fillText(txt,Math.min(Math.max(X(c)-tw/2,0),pw-tw),H-6)}
 // 십자선과 설명
 const hc=hov!=null?Math.floor(hov/bw)+c0:tapI;if(hc!=null&&hc>=c0&&hc<end){const x=X(hc);ctx.strokeStyle=mut;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H-pb);ctx.stroke();ctx.setLineDash([]);
  let txt;if(hc<L){const b=B[hc];txt=`${fmt(b[0],1)} ${fmt(b[0])} 시${usd(b[1])} 고${usd(b[2])} 저${usd(b[3])} 종${usd(b[4])}`}else{const k=fpts.reduce((a,p)=>!a||Math.abs(p[0]-hc)<Math.abs(a[0]-hc)?p:a,null);txt=`${fmt(tOf(hc),1)} ${fmt(tOf(hc))} 예상 ${k?usd(k[1])+' (50% '+usd(k[2][0])+'~'+usd(k[2][1])+')':'-'}`}
  ctx.font='11px system-ui';const tw=ctx.measureText(txt).width+10,tx=Math.min(Math.max(x-tw/2,0),pw-tw);ctx.fillStyle=fg;ctx.fillRect(tx,0,tw,18);ctx.fillStyle=card;ctx.fillText(txt,tx+5,13)}
 if(opt.onDraw)opt.onDraw({first:tOf(Math.max(c0,0)),last:tOf(end-1),n,L,FL})}
// 조작
const P=new Map();let drag=null,pinch=null,lastTap=0,moved=false;
cv.style.touchAction='none';
cv.addEventListener('pointerdown',e=>{cv.setPointerCapture(e.pointerId);P.set(e.pointerId,e.clientX);moved=false;
 if(P.size==1){drag={x:e.clientX,end};const now=Date.now();if(now-lastTap<300&&D){latest()}lastTap=now}
 if(P.size==2){const xs=[...P.values()];pinch={d:Math.abs(xs[0]-xs[1])||1,n,end};drag=null}});
cv.addEventListener('pointermove',e=>{const r=cv.getBoundingClientRect();if(!P.has(e.pointerId)){if(e.pointerType=='mouse'){hov=e.clientX-r.left;draw()}return}
 P.set(e.pointerId,e.clientX);if(!D)return;const bw=(cv.clientWidth-60)/n;
 if(pinch&&P.size==2){const xs=[...P.values()],d=Math.abs(xs[0]-xs[1])||1;const right=pinch.end;n=Math.round(pinch.n*pinch.d/d);end=right;moved=true;draw()}
 else if(drag){const dx=e.clientX-drag.x;if(Math.abs(dx)>4)moved=true;end=Math.round(drag.end-dx/bw);draw()}});
const up_=e=>{const r=cv.getBoundingClientRect();if(drag&&!moved&&e.pointerType!='mouse'){const bw=(cv.clientWidth-60)/n;tapI=Math.floor((e.clientX-r.left)/bw)+end-n;draw()}P.delete(e.pointerId);if(P.size<2)pinch=null;if(!P.size)drag=null};
cv.addEventListener('pointerup',up_);cv.addEventListener('pointercancel',up_);cv.addEventListener('pointerleave',()=>{hov=null;draw()});
cv.addEventListener('wheel',e=>{e.preventDefault();if(!D)return;const r=cv.getBoundingClientRect(),fx=Math.min(Math.max((e.clientX-r.left)/(cv.clientWidth-60),0),1);
 const at=end-n+fx*n;n=Math.round(n*(e.deltaY>0?1.15:1/1.15));n=Math.max(15,n);end=Math.round(at+(1-fx)*n);draw()},{passive:false});
function latest(){if(!D)return;const L=D.bars.length;end=L+FD;n=Math.min(opt.initN||90,L)+FD;tapI=null;draw()}
function zoom(f){n=Math.round(n*f);draw()}
addEventListener('resize',draw);
return {set,draw,zoom,latest,get data(){return D}}};
"""
