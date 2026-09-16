(()=>{
"use strict";
const $=id=>document.getElementById(id), M=window.StaterMath, NS="http://www.w3.org/2000/svg";
const initial=JSON.parse($("bootstrap").textContent);let D=initial,live=!initial,busy=false,timer=null,lastWidth=0,selectedHour=0;
const state={hours:24,model:"",effort:"",excludeMonitor:false,excludeInternal:false,task:null,...(initial?.ui||{})};
let rankingExpanded=false;
const hiddenQuota=new Set(),fmt=new Intl.NumberFormat("zh-CN");
const n=x=>fmt.format(Math.round(x)),compact=x=>x>=1e8?(x/1e8).toFixed(2)+" 亿":x>=1e4?(x/1e4).toFixed(2)+" 万":n(x);
const percent=(a,b)=>b?(100*a/b).toFixed(1)+"%":"—";
const esc=x=>String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const date=(t,full=false)=>new Intl.DateTimeFormat("zh-CN",{timeZone:"UTC",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",...(full?{second:"2-digit"}:{}),hour12:false}).format(new Date(t+D.timezoneOffset*60000));
const time=t=>new Intl.DateTimeFormat("zh-CN",{timeZone:"UTC",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(t+D.timezoneOffset*60000));
const zone=()=>D.timezone==="+08:00"?"北京时间":"UTC"+D.timezone;
const pairs=t=>t.modelEfforts.map(M.modelEffortLabel).join(" / ");
const colors=["var(--teal)","var(--blue)","var(--orange)"];
function add(parent,tag,attributes={},text){const e=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attributes))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;parent.append(e);return e;}
function view(){return D.views[String(state.hours)];}
function filtered(interval){return M.filter(interval.tasks,state,D.monitorId);}
function allTasks(){return view().intervals.flatMap(filtered);}
function hideTip(){$("tooltip").hidden=true;}
function tip(event,html){
 const e=$("tooltip");e.innerHTML=html;e.hidden=false;
 const x=event.clientX||16,y=event.clientY||100;
 e.style.left=Math.max(8,Math.min(x+14,innerWidth-e.offsetWidth-8))+"px";
 e.style.top=Math.max(8,Math.min(y+14,innerHeight-e.offsetHeight-8))+"px";
}
function axes(svg,start,end,max,label,height,divisions=4){
 const width=svg.getBoundingClientRect().width||600,left=60,right=width-16,top=26,bottom=height-44;
 svg.replaceChildren();svg.setAttribute("viewBox","0 0 "+width+" "+height);svg.setAttribute("height",height);
 const x=t=>left+(t-start)/(end-start)*(right-left),y=v=>bottom-v/(max||1)*(bottom-top);
 for(let i=0;i<=divisions;i++){const v=max*i/divisions;add(svg,"line",{x1:left,y1:y(v),x2:right,y2:y(v),class:"grid"});add(svg,"text",{x:left-7,y:y(v)+4,"text-anchor":"end"},label==="剩余 (%)"?n(v):v>=1e6?(v/1e6).toFixed(v%1e6?1:0)+"M":v>=1e3?(v/1e3).toFixed(v%1e3?1:0)+"k":n(v));}
 const ticks=width<440?3:width<750?4:6;
 for(let i=0;i<ticks;i++){const t=start+(end-start)*i/(ticks-1);add(svg,"text",{x:x(t),y:bottom+23,"text-anchor":i===0?"start":i===ticks-1?"end":"middle"},width<440&&state.hours===24?time(t):date(t));}
 add(svg,"text",{x:left,y:14,class:"axis-title"},label);add(svg,"text",{x:right,y:height-3,"text-anchor":"end",class:"axis-title"},zone());
 return {width,left,right,top,bottom,x,y};
}
function inspectHour(index,event){
 const interval=view().intervals[index],b=M.breakdown(filtered(interval));
 $("hour-picker").value=String(index);selectedHour=index;
 const rows=b.top.map(t=>'<div class="tip-row"><span class="tip-name">'+esc(t.title)+'<small class="tip-detail">'+esc(pairs(t))+'</small></span><span>'+n(t.total)+' · '+percent(t.total,b.total)+'</span></div>').join("");
 const others=b.otherCount?'<div class="tip-row"><span>其他 '+b.otherCount+' 个对话</span><span>'+n(b.other)+' · '+percent(b.other,b.total)+'</span></div>':"";
 tip(event,"<strong>"+date(interval.start)+" — "+time(interval.end)+"</strong><div class='tip-total'>合计 "+n(b.total)+" Token · "+b.all.length+" 个对话</div>"+rows+others+(b.total?"":"本小时未发现符合筛选条件的记录")+"<div class='tip-foot'>点击查看完整分对话明细</div>");
}
function openHour(index,show=true){
 const i=view().intervals[index];if(!i)return;
 selectedHour=index;const tasks=filtered(i),b=M.breakdown(tasks),tot=M.sum(tasks);
 $("hour-title").textContent=date(i.start)+" — "+time(i.end)+" · "+zone();
 $("hour-summary").textContent=n(tot.total)+" Token · "+b.all.length+" 个对话 · 缓存输入 "+n(tot.cached)+" · 输出 "+n(tot.output);
 $("hour-table").innerHTML=b.all.map(t=>'<tr><td>'+esc(t.title)+'<div class="small muted">'+esc(pairs(t))+'</div></td><td class="num">'+n(t.total)+'</td><td class="num mobile-hide">'+n(t.cached)+'</td><td class="num mobile-hide">'+n(t.output)+'</td><td class="num">'+percent(t.total,tot.total)+'</td></tr>').join("")||'<tr><td colspan="5">本小时未发现符合条件的记录。</td></tr>';
 hideTip();if(show&&!$("hour-dialog").open)$("hour-dialog").showModal();
}
function drawUsage(){
 const v=view(),svg=$("usage-chart"),totals=v.intervals.map(i=>M.sum(filtered(i))),peak=Math.max(1,...totals.map(t=>t.total));
 const scale=M.usageScale(peak),a=axes(svg,v.start,v.end,scale.max,"Token",scale.height,scale.steps);
 v.intervals.forEach((i,index)=>{const t=totals[index],x=a.x(i.start),w=Math.max(.6,a.x(i.end)-x-(state.hours===168?1:3));let sum=0;
 for(const [value,color] of [[t.cached,"var(--blue)"],[Math.max(0,t.input-t.cached),"var(--teal)"],[t.output,"var(--orange)"]]){add(svg,"rect",{x,y:a.y(sum+value),width:w,height:Math.max(0,a.y(sum)-a.y(sum+value)),fill:color});sum+=value;}
 });
 const guide=add(svg,"rect",{x:0,y:a.top,width:0,height:a.bottom-a.top,fill:"var(--teal)",opacity:.12,"pointer-events":"none"});
 const overlay=add(svg,"rect",{x:a.left,y:a.top,width:a.right-a.left,height:a.bottom-a.top,fill:"transparent","data-hour-overlay":"true"});
 const indexAt=e=>{const r=overlay.getBoundingClientRect(),t=v.start+(e.clientX-r.left)/r.width*(v.end-v.start);let index=v.intervals.findIndex(i=>t>=i.start&&t<i.end);return index<0?t<v.start?0:v.intervals.length-1:index;};
 overlay.onpointermove=e=>{const index=indexAt(e),i=v.intervals[index];guide.setAttribute("x",a.x(i.start));guide.setAttribute("width",a.x(i.end)-a.x(i.start));inspectHour(index,e);};
 overlay.onpointerleave=()=>{guide.setAttribute("width",0);hideTip();};
 overlay.onclick=e=>openHour(indexAt(e));
 const picker=$("hour-picker"),previous=picker.value;picker.replaceChildren();
 v.intervals.forEach((i,index)=>{const option=document.createElement("option");option.value=String(index);option.textContent=date(i.start)+" — "+time(i.end)+" · "+compact(totals[index].total);picker.append(option);});
 picker.value=String(Math.min(Number(previous||v.intervals.length-1),v.intervals.length-1));
}
function drawQuota(){
 const v=view(),points=D.quota.filter(p=>p.t>=v.start&&p.t<=v.end),svg=$("quota-chart"),a=axes(svg,v.start,v.end,100,"剩余 (%)",215);
 const latest=D.quota.at(-1),codex=latest?.windows.find(w=>w.key==="codex:primary");
 $("quota-status").textContent=latest?"最近账号采样 "+date(latest.t)+" · 距面板更新 "+Math.max(0,Math.round((D.generatedAt-latest.t)/60000))+" 分钟"+(codex?" · Codex 剩余 "+codex.remaining+"%":""):"暂无额度历史；可在配置中指定原巡检记录目录。";
 $("quota-note").textContent="每小时巡检更新账号额度；本机 Token 由面板单独刷新。";
 const series=[...new Map(points.flatMap(p=>p.windows.map(w=>[w.key,w.name]))).entries()].sort((a,b)=>a[0].localeCompare(b[0]));
 $("quota-legend").replaceChildren();
 series.forEach(([key,name],index)=>{
  const button=document.createElement("button");button.type="button";button.setAttribute("aria-pressed",String(!hiddenQuota.has(key)));button.innerHTML='<i style="background:'+colors[index%3]+'"></i>'+esc(name);button.onclick=()=>{if(hiddenQuota.has(key))hiddenQuota.delete(key);else hiddenQuota.add(key);drawQuota();};$("quota-legend").append(button);
  if(hiddenQuota.has(key))return;
  let d="",last=null;
  for(const p of points){const w=p.windows.find(w=>w.key===key);if(!w||w.remaining==null){last=null;continue;}
   const gap=!last||last.p.account!==p.account||(key==="codex:primary"&&Math.abs((last.w.reset||0)-(w.reset||0))>60);
   d+=(gap?"M":"L")+a.x(p.t)+","+a.y(w.remaining);
   add(svg,"circle",{cx:a.x(p.t),cy:a.y(w.remaining),r:2.5,fill:colors[index%3]});last={p,w};
  }
  add(svg,"path",{d,fill:"none",stroke:colors[index%3],"stroke-width":2,"stroke-dasharray":index===2?"5 4":"none"});
 });
 if(!points.length){add(svg,"text",{x:(a.left+a.right)/2,y:(a.top+a.bottom)/2,"text-anchor":"middle"},"此范围暂无额度历史");return;}
 const overlay=add(svg,"rect",{x:a.left,y:a.top-6,width:a.right-a.left,height:a.bottom-a.top+12,fill:"transparent"});
 const inspect=e=>{const r=overlay.getBoundingClientRect(),t=v.start+(e.clientX-r.left)/r.width*(v.end-v.start),p=points.reduce((best,p)=>Math.abs(p.t-t)<Math.abs(best.t-t)?p:best,points[0]);
 tip(e,"<strong>额度采样 "+date(p.t)+"</strong>"+p.windows.filter(w=>!hiddenQuota.has(w.key)).map(w=>'<div class="tip-row"><span>'+esc(w.name)+'</span><span>'+w.remaining+'%</span></div>').join(""));};
 overlay.onpointermove=inspect;overlay.onclick=inspect;overlay.onpointerleave=hideTip;
}
function optionsFor(id,values,selected,allLabel,label=x=>x){
 const choices=[...values];if(selected&&!choices.includes(selected))choices.push(selected);
 $(id).innerHTML='<option value="">'+allLabel+'</option>'+choices.map(value=>'<option value="'+esc(value)+'">'+esc(label(value)+(values.includes(value)?"":"（当前无记录）"))+'</option>').join("");
 $(id).value=selected;
}
function renderComparison(items,tot,conversationCount){
 const groups=M.byModelEffort(items);
 $("comparison-count").textContent=groups.length+" 个分组";
 $("comparison").innerHTML=groups.map(g=>'<tr><td>'+esc(g.model)+'</td><td>'+esc(M.effortLabel(g.effort))+'</td>'+[g.total,g.input,g.cached,g.output,g.reasoning,g.count].map(value=>'<td class="num">'+n(value)+'</td>').join("")+'</tr>').join("")||'<tr><td colspan="8">当前筛选没有符合条件的用量记录。</td></tr>';
 $("comparison-total").innerHTML='<tr><th colspan="2">合计</th>'+[tot.total,tot.input,tot.cached,tot.output,tot.reasoning,conversationCount].map(value=>'<td class="num">'+n(value)+'</td>').join("")+'</tr>';
 window.StaterShare.render(groups);
}
function render(){
 if(!D)return;
 const v=view(),available=v.intervals.flatMap(i=>i.tasks);
 optionsFor("model",[...new Set(available.map(t=>t.model))].sort(),state.model,"全部模型");
 const effortOrder=["none","minimal","low","medium","high","xhigh","max","ultra","unknown"];
 const efforts=[...new Set(M.filter(available,{...state,effort:""},D.monitorId).map(M.effort))].sort((a,b)=>(effortOrder.includes(a)?effortOrder.indexOf(a):effortOrder.length)-(effortOrder.includes(b)?effortOrder.indexOf(b):effortOrder.length)||a.localeCompare(b));
 optionsFor("effort",efforts,state.effort,"全部强度",M.effortLabel);
 $("exclude-monitor").checked=state.excludeMonitor;$("exclude-internal").checked=state.excludeInternal;
 $("exclude-monitor").closest("label").hidden=!D.monitorId;
 document.querySelectorAll("[data-hours]").forEach(b=>b.setAttribute("aria-pressed",String(Number(b.dataset.hours)===state.hours)));
 const items=allTasks(),tot=M.sum(items),ranked=M.conversations(items);
 $("filter-empty").hidden=items.length>0;$("filter-empty").textContent="当前时间范围与筛选组合没有用量记录；已保留你的筛选，可更换时间范围、模型、推理强度或恢复全部。";
 $("total").textContent=compact(tot.total);$("total-exact").textContent=n(tot.total)+" Token";
 $("cache").textContent=percent(tot.cached,tot.input);$("output").textContent=compact(tot.output);$("reasoning").textContent="其中推理 "+n(tot.reasoning);$("count").textContent=ranked.length;
 $("range-label").textContent=date(v.start)+" — "+date(v.end)+" · "+zone()+" · 首尾小时可能不完整";
 $("updated").textContent=D.machine+" · 本机数据更新于 "+date(D.generatedAt,true);
 $("mode").textContent=live?"每 "+D.refreshSeconds+" 秒刷新":"离线快照";
 $("refresh").hidden=!live;
 $("error").hidden=!D.warnings.length;$("error").textContent=D.warnings.join("；");
 const selected=(D.views["168"]||v).intervals.flatMap(i=>i.tasks).find(t=>t.id===state.task);
 $("selection").hidden=!state.task;$("selected-task").textContent=state.task?"筛选对话："+(selected?.title||state.task):"";
 const max=ranked[0]?.total||1;
 const visibleRanked=rankingExpanded?ranked:ranked.slice(0,5);
 $("ranking").innerHTML=visibleRanked.map(t=>'<tr><td><button data-task="'+esc(t.id)+'">'+esc(t.title)+'</button><div class="small muted">'+esc(t.project)+(t.internal?" · 内部审批":"")+(t.id===D.monitorId?" · 本统计任务":"")+'</div><div class="small muted narrow-models">'+esc(pairs(t))+'</div><div class="rank-bar"><i style="width:'+(t.total/max*100)+'%"></i></div></td><td class="optional">'+esc(pairs(t))+'</td><td class="num">'+n(t.total)+'</td><td class="num mobile-hide">'+n(t.cached)+'</td><td class="num optional">'+n(t.output)+'</td><td class="num mobile-hide">'+percent(t.total,tot.total)+'</td></tr>').join("")||'<tr><td colspan="6">当前范围没有符合条件的日志记录。</td></tr>';
 $("ranking").querySelectorAll("[data-task]").forEach(b=>b.onclick=()=>{state.task=state.task===b.dataset.task?null:b.dataset.task;updateFilters();});
 $("rank-count").textContent=ranked.length+" 个对话"+(ranked.length>5&&!rankingExpanded?" · 显示前 5 条":"");
 const rankingToggle=$("ranking-toggle");
 rankingToggle.hidden=ranked.length<=5;
 rankingToggle.setAttribute("aria-expanded",String(rankingExpanded));
 rankingToggle.textContent=rankingExpanded?"收起，显示前 5 条":"展开其余 "+Math.max(0,ranked.length-5)+" 条";
 renderComparison(items,tot,ranked.length);
 $("coverage").textContent=v.firstEvent?"窗口内首末可见用量事件："+date(v.firstEvent)+" — "+date(v.lastEvent)+"。没有事件的小时显示 0，不代表其他机器或账号没有消耗。":"当前窗口没有可用 Token 事件；请检查数据目录、时间范围或日志落盘情况。";
 $("scan-info").textContent="最近读取 "+D.scan.filesChanged+" 个变更日志，"+n(D.scan.bytesRead)+" 字节，用时 "+D.scan.seconds+" 秒。";
 $("footer").textContent=live?"本地读取，不调用模型。再次打开页面会查询最新数据。":"导出于 "+date(D.generatedAt,true)+"，此 HTML 可离线交互。";
 drawUsage();drawQuota();
 if($("hour-dialog").open)openHour(Math.min(selectedHour,v.intervals.length-1),false);
}
async function load(force=false){
 if(!live||busy)return;busy=true;$("refresh").disabled=true;$("refresh").textContent=D?"刷新中…":"首次建立索引…";
 try{const response=await fetch("/api/data"+(force?"?force=1":""),{cache:"no-store"});const data=await response.json();if(!response.ok)throw Error(data.error||"读取失败");D=data;render();}
 catch(error){$("error").hidden=false;$("error").textContent="刷新失败"+(D?"，保留上次数据":"")+"："+error.message;}
 finally{busy=false;$("refresh").disabled=false;$("refresh").textContent="立即刷新";clearTimeout(timer);timer=setTimeout(()=>{if(document.hidden)schedule();else load();},(D?.refreshSeconds||60)*1000);}
}
function schedule(){clearTimeout(timer);timer=setTimeout(()=>{if(!document.hidden)load();else schedule();},(D?.refreshSeconds||60)*1000);}
function exportHTML(){
 if(!D)return;
 const clone=document.documentElement.cloneNode(true);
 clone.querySelector("#bootstrap").textContent=JSON.stringify({...D,ui:state}).replace(/</g,"\\u003c");
 clone.querySelector("#tooltip").hidden=true;clone.querySelector("#hour-dialog").removeAttribute("open");
 const content="<!doctype html>\n"+clone.outerHTML,blob=new Blob([content],{type:"text/html;charset=utf-8"}),url=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=url;a.download="codex-"+(state.hours===168?"7days":"24hours")+"-"+new Date(D.generatedAt).toISOString().slice(0,10)+".html";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function updateFilters(){rankingExpanded=false;render();}
$("ranking-toggle").onclick=()=>{rankingExpanded=!rankingExpanded;render();};
document.querySelectorAll("[data-hours]").forEach(b=>b.onclick=()=>{state.hours=Number(b.dataset.hours);updateFilters();});
$("model").onchange=()=>{state.model=$("model").value;updateFilters();};
$("effort").onchange=()=>{state.effort=$("effort").value;updateFilters();};
$("exclude-monitor").onchange=()=>{state.excludeMonitor=$("exclude-monitor").checked;updateFilters();};
$("exclude-internal").onchange=()=>{state.excludeInternal=$("exclude-internal").checked;updateFilters();};
$("reset").onclick=()=>{Object.assign(state,{hours:24,model:"",effort:"",excludeMonitor:false,excludeInternal:false,task:null});updateFilters();};
$("clear-task").onclick=()=>{state.task=null;updateFilters();};
$("hour-open").onclick=()=>{if(D)openHour(Number($("hour-picker").value));};
$("close-dialog").onclick=()=>$("hour-dialog").close();
$("refresh").onclick=()=>load(true);$("export").onclick=exportHTML;
window.addEventListener("scroll",hideTip,{passive:true});
document.addEventListener("visibilitychange",()=>{if(live&&!document.hidden)load();});
new ResizeObserver(entries=>{const width=entries[0].contentRect.width;if(width!==lastWidth){lastWidth=width;if(D){drawUsage();drawQuota();}}}).observe($("stater"));
if(D)render();else load(true);
})();
