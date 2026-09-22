(function(){
"use strict";
window.StaterAccounts=function({getData,live,onSaved}){
 const $=id=>document.getElementById(id),M=window.StaterMath,unknown="__unknown__";
 let draft=[],revision=0,editing=null,saving=false,sequence=0;
 const label=a=>a===unknown?"未知账号":a;
 const local=t=>M.localDateTime(t,getData().timezoneOffset).replace("T"," ");
 function status(text){$("accounts-status").textContent=text;}
 function error(text){$("accounts-error").textContent=text;$("accounts-error").hidden=!text;}
 function lock(value){saving=value;$("accounts-dialog").querySelectorAll("button,input").forEach(e=>e.disabled=value);$("accounts-name").disabled=value||$("accounts-unknown").checked;}
 function reset(){editing=null;$("accounts-name").value="";$("accounts-unknown").checked=false;$("accounts-name").disabled=false;$("accounts-start").value=M.localDateTime(Date.now(),getData().timezoneOffset);$("accounts-add").textContent="添加到列表";}
 function render(){
  const list=$("accounts-list");list.replaceChildren();
  if(!draft.length){const p=document.createElement("p");p.textContent="尚无标记，所有用量暂归为未知账号。";list.append(p);}
  draft.forEach((mark,index)=>{
   const row=document.createElement("div");row.className="account-period";
   const info=document.createElement("div"),name=document.createElement("strong"),span=document.createElement("div");
   name.textContent=label(mark.account);span.className="small muted";span.textContent=local(mark.start)+" → "+(draft[index+1]?local(draft[index+1].start):"持续生效，直到下一条标记");info.append(name,span);row.append(info);
   if(live){const actions=document.createElement("div");actions.className="actions";
    for(const [title,handler] of [["修改",()=>{editing=index;$("accounts-name").value=mark.account===unknown?"":mark.account;$("accounts-unknown").checked=mark.account===unknown;$("accounts-name").disabled=mark.account===unknown;$("accounts-start").value=M.localDateTime(mark.start,getData().timezoneOffset);$("accounts-add").textContent="更新这条标记";$("accounts-start").focus();}], ["移除",()=>{draft.splice(index,1);reset();render();status("有未保存的修改；移除后，前一条标记会持续到下一条。");}]]){
     const button=document.createElement("button");button.type="button";button.textContent=title;button.onclick=handler;actions.append(button);
    }row.append(actions);
   }list.append(row);
  });
  $("accounts-names").replaceChildren(...[...new Set(draft.map(m=>m.account).filter(a=>a!==unknown))].map(a=>{const o=document.createElement("option");o.value=a;return o;}));
 }
 async function open(){
  if(!getData())return;const ticket=++sequence;error("");reset();
  $("accounts-hint").textContent=(getData().timezone==="+08:00"?"北京时间":"UTC"+getData().timezone)+(live?" · 手工标记账号切换时间":" · 离线快照，仅可查看；修改需回到本机面板");
  $("accounts-form").hidden=!live;$("accounts-save").hidden=!live;
  $("accounts-dialog").showModal();draft=[];render();status("读取中…");lock(true);
  try{let value=getData().accounts||{revision:0,marks:[]};if(live){const r=await fetch("/api/accounts",{cache:"no-store"});value=await r.json();if(!r.ok)throw Error(value.error||"读取失败");}
   if(ticket!==sequence)return;revision=value.revision;draft=value.marks.map(m=>({...m}));render();status(live?"列表中的修改保存后才会影响统计。":"已保存的账号筛选仍可使用。");
  }catch(e){if(ticket===sequence){error(e.message);$("accounts-save").hidden=true;}}
  finally{if(ticket===sequence)lock(false);}
 }
 function close(){if(saving)return;sequence++;$("accounts-dialog").close();}
 $("manage-accounts").onclick=open;$("accounts-close").onclick=close;$("accounts-cancel").onclick=close;
 $("accounts-dialog").oncancel=e=>{e.preventDefault();close();};
 $("accounts-unknown").onchange=()=>{$("accounts-name").disabled=$("accounts-unknown").checked;};
 $("accounts-now").onclick=()=>{$("accounts-start").value=M.localDateTime(Date.now(),getData().timezoneOffset);};
 $("accounts-form").onsubmit=e=>{
  e.preventDefault();error("");const account=$("accounts-unknown").checked?unknown:$("accounts-name").value.trim(),start=M.parseLocalDateTime($("accounts-start").value,getData().timezoneOffset);
  if(!account||account.length>80||(!$("accounts-unknown").checked&&[unknown,"未知账号"].includes(account))){error("请输入 1–80 个字符的账号名称，或勾选未知账号。");return;}
  if(!Number.isFinite(start)||start<0||start>Date.now()+60000){error("请选择有效的开始时间，且不能晚于当前时间。");return;}
  if(draft.some((m,i)=>m.start===start&&i!==editing)){error("此时间已有标记，请修改原记录或选择其他时间。");return;}
  if(editing!==null)draft.splice(editing,1);draft.push({start,account});draft.sort((a,b)=>a.start-b.start);reset();render();status("有未保存的修改，请点击“保存并更新统计”。");
 };
 $("accounts-save").onclick=async()=>{
  error("");if(editing!==null||$("accounts-name").value.trim()||$("accounts-unknown").checked){error("请先点击“添加到列表”或“更新这条标记”，再保存。");return;}
  lock(true);status("保存并更新统计中…");
  try{const r=await fetch("/api/accounts",{method:"POST",headers:{"Content-Type":"application/json","X-Stater-Write":"1"},body:JSON.stringify({revision,marks:draft})});const value=await r.json();if(!r.ok)throw Error(value.error||"保存失败");revision=value.revision;draft=value.marks;
   const refreshed=await onSaved();status(refreshed?"已保存，统计已更新。":"已保存；数据刷新失败，请关闭窗口后点击立即刷新。");render();
  }catch(e){error(e.message);status("未保存，请检查提示后重试。");}finally{lock(false);}
 };
};
})();
