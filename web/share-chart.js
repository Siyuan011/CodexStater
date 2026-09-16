(function(root){
"use strict";
const NS="http://www.w3.org/2000/svg";
const effortHues={none:205,minimal:185,low:175,medium:38,high:162,xhigh:263,max:317,ultra:218,unknown:209};
const number=new Intl.NumberFormat("zh-CN");
function compact(value){if(value>=1e9)return (value/1e9).toFixed(2).replace(/\.?0+$/,"")+"B";if(value>=1e6)return (value/1e6).toFixed(2).replace(/\.?0+$/,"")+"M";if(value>=1e3)return (value/1e3).toFixed(1).replace(/\.?0+$/,"")+"K";return number.format(value);}
function percentage(ratio){return ratio>0&&ratio<.001?"<0.1%":(ratio*100).toFixed(1).replace(/\.0$/,"")+"%";}
function hash(value){let result=2166136261;for(const char of value){result^=char.codePointAt(0);result=Math.imul(result,16777619);}return result>>>0;}
function color(group){const seed=hash(String(group.model)),effort=root.StaterMath.effort(group),base=Object.prototype.hasOwnProperty.call(effortHues,effort)?effortHues[effort]:hash(effort)%360;return `hsl(${(base+seed%21-10+360)%360} ${effort==="unknown"?28:61}% ${47+seed%7}%)`;}
function element(name,attributes={},text){const node=document.createElementNS(NS,name);for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=text;return node;}
function render(groups){
 const chart=document.getElementById("share-chart"),legend=document.getElementById("share-legend"),empty=document.getElementById("share-empty");
 if(!chart||!legend)return;
 const entries=groups.filter(group=>Number.isFinite(group.total)&&group.total>0),total=entries.reduce((value,group)=>value+group.total,0);
 chart.replaceChildren();legend.replaceChildren();
 chart.setAttribute("viewBox","0 0 300 300");
 const title=element("title",{id:"share-chart-title"},"模型与推理强度 Token 用量占比"),description=element("desc",{id:"share-chart-description"},total?`当前筛选共 ${number.format(total)} Token，${entries.length} 个模型与强度组合。各组用量和占比见旁边图例。`:"当前筛选暂无 Token 用量。");
 chart.append(title,description);
 chart.append(element("circle",{cx:150,cy:150,r:112,fill:"none",stroke:"var(--line)","stroke-width":34}));
 const circumference=2*Math.PI*112;
 let offset=0;
 const slices=[];
 entries.forEach((group,index)=>{
  const ratio=group.total/total,label=root.StaterMath.modelEffortLabel(group),sliceColor=color(group),share=percentage(ratio);
  const slice=element("circle",{class:"share-slice",cx:150,cy:150,r:112,fill:"none",stroke:sliceColor,"stroke-width":34,"stroke-dasharray":`${ratio*circumference} ${circumference}`,"stroke-dashoffset":-offset,transform:"rotate(-90 150 150)","data-share-index":index});
  slice.append(element("title",{},`${label}：${number.format(group.total)} Token · ${share}`));
  slices.push(slice);chart.append(slice);offset+=ratio*circumference;
  const row=document.createElement("li");row.className="share-item";row.style.setProperty("--slice-color",sliceColor);row.style.setProperty("--share-ratio",`${ratio*100}%`);
  const swatch=document.createElement("i");swatch.className="share-swatch";swatch.setAttribute("aria-hidden","true");
  const details=document.createElement("div");details.className="share-item-details";
  const name=document.createElement("span");name.className="share-name";name.textContent=label;
  const value=document.createElement("span");value.className="share-token";value.textContent=compact(group.total)+" Token";value.title=number.format(group.total)+" Token";
  const percent=document.createElement("strong");percent.className="share-percent";percent.textContent=share;
  const rail=document.createElement("span");rail.className="share-rail";rail.setAttribute("aria-hidden","true");rail.append(document.createElement("i"));
  details.append(name,value);row.append(swatch,details,percent,rail);legend.append(row);
  row.addEventListener("pointerenter",()=>{slices.forEach((node,i)=>node.classList.toggle("share-dimmed",i!==index));slice.classList.add("share-active");});
  row.addEventListener("pointerleave",()=>{slices.forEach(node=>node.classList.remove("share-dimmed","share-active"));});
 });
 chart.append(element("text",{x:150,y:126,"text-anchor":"middle",class:"share-center-caption"},"当前筛选"));
 chart.append(element("text",{x:150,y:166,"text-anchor":"middle",class:"share-center-total"},compact(total)));
 chart.append(element("text",{x:150,y:191,"text-anchor":"middle",class:"share-center-unit"},"Token"));
 if(empty)empty.hidden=total>0;
 legend.hidden=total===0;
}
root.StaterShare={render};
})(window);
