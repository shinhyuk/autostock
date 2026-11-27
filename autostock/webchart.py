"""매매 탭(가상·모의·실계좌·시간외)의 가격 차트 시작 스크립트. 그리기는 공용 차트(chartjs.CHART_CORE)."""
CHART_JS = r"""
(()=>{const cv=document.getElementById('chart');if(!cv)return;
const q=new URLSearchParams(location.search),K=q.get('k'),M=cv.dataset.mode;let sym=cv.dataset.sym,span=120;
try{span=+(localStorage.getItem('span')||120)}catch(e){}
const msg=document.getElementById('cmsg');const iv=()=>span>0?span:400;
const C=MakeChart(cv,{initN:iv()});
async function load(reset){let D;try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=${M}&sym=${sym}&span=${span}${window.chartQ||''}`);D=await r.json()}catch(e){D={error:'연결 실패'}}
 if(D.v&&window.APPV&&D.v!==window.APPV){location.reload();return}   // 서버가 업데이트되면 새 화면으로
 if(window.onChart)window.onChart(D);
 if(!D.bars||D.bars.length<2){msg.textContent=D.error?'차트를 불러오지 못했습니다: '+D.error:'표시할 시세가 아직 없습니다 (봇이 1분봉을 모으는 중)';return}
 C.set(D,reset,iv());const L=D.bars[D.bars.length-1],a=D.fc&&D.fc.acc;
 msg.textContent=`${sym} 1분봉 · 현재 ${'$'+L[4].toFixed(2)} · 드래그=시간 이동 · 두 손가락/휠=확대축소 · 두 번 누르면 최신`+
  (D.fc?` · 예상: ${D.fc.label}${a&&a.n?` (지난 ${a.n}번 채점${a.dir!=null&&D.fc.model!='flat'?', 방향 '+Math.round(a.dir)+'%':''}${a.in50!=null?', 50% 범위 '+Math.round(a.in50)+'%':''})`:''}`:'')+(D.note?' · '+D.note:'')}
window.chartReload=()=>load(true);
const pick=(sel,f)=>document.querySelectorAll(sel).forEach(a=>a.addEventListener('click',()=>{document.querySelectorAll(sel).forEach(x=>x.classList.toggle('on',x==a));f(a);load(true)}));
pick('button[data-sym]',a=>sym=a.dataset.sym);pick('button[data-span]',a=>{span=+a.dataset.span;try{localStorage.setItem('span',span)}catch(e){}});
document.querySelectorAll('button[data-span]').forEach(a=>a.classList.toggle('on',+a.dataset.span==span));
document.querySelectorAll('[data-czoom]').forEach(b=>b.addEventListener('click',()=>C.zoom(b.dataset.czoom=='in'?0.7:1.4)));
load(true);setInterval(()=>load(false),10000)})();
"""
