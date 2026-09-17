(function(root){
"use strict";
function sum(items){return items.reduce((a,t)=>{for(const k of ["input","cached","output","reasoning","total"])a[k]+=t[k]||0;return a},{input:0,cached:0,output:0,reasoning:0,total:0});}
const effortNames={none:"无",minimal:"最低",low:"低",medium:"中",high:"高",xhigh:"超高",max:"Max",ultra:"Ultra",unknown:"未记录"};
function effort(t){return typeof t.effort==="string"&&t.effort.trim()?t.effort.trim().toLowerCase():"unknown";}
function effortLabel(value){return Object.prototype.hasOwnProperty.call(effortNames,value)?effortNames[value]:value;}
function modelEffortLabel(pair){return pair.model+" · "+effortLabel(effort(pair));}
function pairKey(t){return JSON.stringify([t.model,effort(t)]);}
function filter(items,state,monitorId){return items.filter(t=>(!state.model||t.model===state.model)&&(!state.effort||effort(t)===state.effort)&&(!state.excludeMonitor||t.id!==monitorId)&&(!state.excludeInternal||!t.internal)&&(!state.task||t.id===state.task));}
function conversations(items){const map=new Map();for(const t of items){if(!map.has(t.id))map.set(t.id,{...t,models:new Set(),modelEfforts:new Map(),input:0,cached:0,output:0,reasoning:0,total:0});const g=map.get(t.id);g.models.add(t.model);g.modelEfforts.set(pairKey(t),{model:t.model,effort:effort(t)});for(const k of ["input","cached","output","reasoning","total"])g[k]+=t[k]||0;}return [...map.values()].map(t=>({...t,models:[...t.models].sort(),modelEfforts:[...t.modelEfforts.values()].sort((a,b)=>modelEffortLabel(a).localeCompare(modelEffortLabel(b)))})).sort((a,b)=>b.total-a.total);}
function byModelEffort(items){const map=new Map();for(const t of items){const key=pairKey(t);if(!map.has(key))map.set(key,{model:t.model,effort:effort(t),ids:new Set(),input:0,cached:0,output:0,reasoning:0,total:0});const g=map.get(key);g.ids.add(t.id);for(const k of ["input","cached","output","reasoning","total"])g[k]+=t[k]||0;}return [...map.values()].map(({ids,...t})=>({...t,count:ids.size})).sort((a,b)=>b.total-a.total||modelEffortLabel(a).localeCompare(modelEffortLabel(b)));}
function breakdown(items,limit=8){const all=conversations(items),top=all.slice(0,limit),total=sum(items).total;return{all,top,total,other:total-top.reduce((s,t)=>s+t.total,0),otherCount:Math.max(0,all.length-limit)};}
function usageScale(peak){
 const tick=2500000,pixelsPerStep=57.5;
 const steps=Math.max(4,Math.ceil((Number.isFinite(peak)&&peak>0?peak:0)/tick));
 return{tick,steps,max:steps*tick,height:70+steps*pixelsPerStep};
}
function localDateTime(timestamp,offset){
 if(!Number.isFinite(timestamp)||!Number.isFinite(offset))return "";
 return new Date(timestamp+offset*60000).toISOString().slice(0,16);
}
function parseLocalDateTime(value,offset){
 const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
 if(!match||!Number.isFinite(offset))return NaN;
 const [,year,month,day,hour,minute]=match.map(Number);
 if(year<1||month<1||month>12||day<1||day>31||hour>23||minute>59)return NaN;
 const date=new Date(0);date.setUTCFullYear(year,month-1,day);date.setUTCHours(hour,minute,0,0);
 if(date.toISOString().slice(0,16)!==value)return NaN;
 return date.getTime()-offset*60000;
}
function rangeError(start,end,now=Date.now()){
 if(!Number.isFinite(start)||!Number.isFinite(end))return "请填写有效的开始和结束日期、时间。";
 if(start<0)return "开始时间不能早于 1970 年。";
 if(start>=end)return "结束时间必须晚于开始时间。";
 if(end-start>366*86400000)return "单次最多查询 366 天，请缩短时间范围。";
 if(end>now+60000)return "结束时间不能晚于当前时间。";
 return "";
}
const api={sum,effort,effortLabel,modelEffortLabel,filter,conversations,byModelEffort,breakdown,usageScale,localDateTime,parseLocalDateTime,rangeError};
if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.StaterMath=api;
})(typeof window!=="undefined"?window:globalThis);
