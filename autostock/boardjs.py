"""차트 탭 시작 스크립트: 종목·봉 단위 선택, 공용 차트(chartjs.CHART_CORE), AI 계획(버튼을 누를 때만)."""
BOARD_JS = r"""
(()=>{const cv=document.getElementById('bc');if(!cv)return;
const q=new URLSearchParams(location.search),K=q.get('k');let sym='SOXL',tf='5m',D=null,PLAN=null;
try{sym=localStorage.getItem('bsym')||sym;tf=localStorage.getItem('btf')||tf}catch(e){}
const usd=v=>'$'+(v>=1000?v.toFixed(0):v.toFixed(2));
const C=MakeChart(cv,{initN:90});
function mark(){document.querySelectorAll('[data-bsym]').forEach(b=>b.classList.toggle('on',b.dataset.bsym==sym));document.querySelectorAll('[data-btf]').forEach(b=>b.classList.toggle('on',b.dataset.btf==tf))}
function withPlan(d){if(!d)return d;const P=PLAN&&!PLAN.error&&!PLAN.none?PLAN:null;d.plan=P;d.lines=[];d.bands=[];
 if(P){const k=P.action=='BUY'?'buy':P.action=='AVOID'?'avoid':'wait';d.bands=[{lo:P.entry_lo,hi:P.entry_hi,k,l:(k=='buy'?'진입 ':k=='avoid'?'회피 ':'대기 ')+usd(P.entry_lo)+'~'+usd(P.entry_hi)}];
  d.lines=[{v:P.target,k:'take',l:'목표'},{v:P.stop,k:'stop',l:'손절'}]}return d}
async function load(reset){const msg=document.getElementById('bmsg');try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=board&sym=${sym}&tf=${tf}`);const nd=await r.json();
  if(nd.error&&!(nd.bars||[]).length){msg.textContent='차트를 불러오지 못했습니다: '+nd.error;return}
  D=withPlan(nd);C.set(D,reset);const L=D.bars.length,lt=D.bars[L-1][0],a=D.fc&&D.fc.acc;
  msg.textContent=`${sym} ${document.querySelector('[data-btf].on')?.textContent||tf} · 마지막 ${new Date(lt).toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Seoul'})}${D.kis_bars?' (최근 '+D.kis_bars+'개는 한국투자증권)':''} · 드래그=시간 이동(왼쪽으로 끌면 더 먼 미래) · 두 손가락/휠=확대축소 · 두 번 누르면 최신`;
  const fi=document.getElementById('bfc');if(D.fc){const m=a&&a.models||{};const top=Object.entries(m).sort((x,y)=>x[1].err-y[1].err).slice(0,3);
   fi.innerHTML=`<b>예상선</b>: ${D.fc.label}${D.fc.model!='flat'&&a&&a.dir!=null?' · 방향 적중 '+Math.round(a.dir)+'%':''}${a&&a.in50!=null?' · 50% 범위 적중 '+Math.round(a.in50)+'%':''} (지난 ${a?a.n:0}번 예측을 실제와 비교해 채점, 범위 폭 ×${D.fc.w})<br>`+
    `<span class=note>서버가 예측을 기록해 두고, 후보 방식 ${Object.keys(m).length}가지 중 최근 실제 오차가 가장 작은 것을 스스로 고릅니다. 차트의 가는 선은 지난 예측(초록=맞음, 주황=틀림, 회색=진행 중). `+
    (top.length?'오차 작은 순: '+top.map(([k,v])=>`${v.label||k} ${v.err}`).join(' · '):'')+`</span>`}else fi.innerHTML='<span class=note>예상선을 준비 중입니다 (서버가 기록을 시작하면 30초 안에 나타남)</span>'}catch(e){msg.textContent='연결 실패'}}
async function plan(ask){const el=document.getElementById('bplan'),btn=document.getElementById('bask');const s0=sym,t0=tf;
 if(ask){btn.disabled=true;btn.textContent='계획 세우는 중… (10초쯤)'}
 try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=board&what=plan&sym=${sym}&tf=${tf}${ask?'&ask=1':''}`);const p=await r.json();if(s0!=sym||t0!=tf)return;
 btn.disabled=false;btn.textContent='AI 계획 받기';PLAN=p;if(D){withPlan(D);C.draw()}
 if(p.none){el.innerHTML=`<div class=note>${sym} ${document.querySelector('[data-btf].on')?.textContent||tf} 계획이 아직 없습니다.</div>`;return}
 if(p.error){el.innerHTML=`<div class=note>계획을 세우지 못했습니다: ${p.error}</div>`;return}
 const name={BUY:sym+' 매수',AVOID:sym+' 사지 않기 (하락 쪽'+(sym=='SOXL'?' · SOXS 고려':sym=='SOXS'?' · SOXL 고려':'')+')',WAIT:'관망 (기다리기)'}[p.action];
 const cls=p.action=='BUY'?'up':p.action=='AVOID'?'dn':'mut',mid=(p.entry_lo+p.entry_hi)/2,rr=Math.abs(p.target-mid)/Math.max(Math.abs(mid-p.stop),1e-9);
 el.innerHTML=`<div class='big2 ${cls}'>${name}</div><div class=sub>확신도 ${Math.round(p.confidence*100)}% · 보유 ${p.horizon} · ${p.src}${p.at?' · '+new Date(p.at*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Seoul'})+' 기준':''}</div>`+
  `<dl class=kv><dt>${p.action=='BUY'?'진입':'기다릴 가격대'}</dt><dd>${usd(p.entry_lo)} ~ ${usd(p.entry_hi)}</dd><dt>목표</dt><dd class=up>${usd(p.target)}</dd><dt>손절</dt><dd class=dn>${usd(p.stop)}</dd><dt>손익비</dt><dd>${rr.toFixed(1)} : 1</dd></dl>`+
  `<div class=note>${(p.reasons||[]).map(x=>'· '+x).join('<br>')}</div>`+(p.long_view?`<div class=note><b>장기</b>: ${p.long_view}</div>`:'')+(p.note?`<div class='note warnt'>${p.note}</div>`:'')}catch(e){btn.disabled=false;btn.textContent='AI 계획 받기';el.innerHTML='<div class=note>계획 연결 실패</div>'}}
document.querySelectorAll('[data-bzoom]').forEach(b=>b.addEventListener('click',()=>C.zoom(b.dataset.bzoom=='in'?0.7:1.4)));
document.querySelectorAll('[data-bsym]').forEach(b=>b.addEventListener('click',()=>{sym=b.dataset.bsym;try{localStorage.setItem('bsym',sym)}catch(e){}mark();PLAN=null;load(true);plan(false)}));
document.querySelectorAll('[data-btf]').forEach(b=>b.addEventListener('click',()=>{tf=b.dataset.btf;try{localStorage.setItem('btf',tf)}catch(e){}mark();PLAN=null;load(true);plan(false)}));
document.getElementById('bask').addEventListener('click',()=>plan(true));
mark();load(true);plan(false);setInterval(()=>load(false),10000)})();
"""
