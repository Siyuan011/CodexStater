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
const api={sum,effort,effortLabel,modelEffortLabel,filter,conversations,byModelEffort,breakdown,usageScale};
if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.StaterMath=api;
})(typeof window!=="undefined"?window:globalThis);
