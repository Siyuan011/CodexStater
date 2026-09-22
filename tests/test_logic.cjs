const assert=require('node:assert/strict');
const M=require('../web/logic.js');
const tasks=Array.from({length:12},(_,i)=>({id:'t'+i,title:'Task '+i,model:'a',input:10+i,cached:5,output:2,reasoning:1,total:12+i,internal:i===0}));
tasks.push({...tasks[1],model:'b'});
const b=M.breakdown(tasks);
assert.equal(b.top.length,8);
assert.equal(b.all.length,12);
assert.equal(b.otherCount,4);
assert.equal(b.total,b.top.reduce((s,t)=>s+t.total,0)+b.other);
assert.equal(b.all.find(t=>t.id==='t1').total,26);
assert.equal(b.all.find(t=>t.id==='t1').models.length,2);
const state={model:'b',excludeMonitor:false,excludeInternal:true,task:null};
assert.equal(M.filter(tasks,state,'t1').length,1);
state.excludeMonitor=true;
assert.equal(M.filter(tasks,state,'t1').length,0);
assert.equal(M.sum([]).total,0);

const base={title:'Shared conversation',project:'project',internal:false};
const usage=(id,model,effort,input,output,extra={})=>({...base,id,model,effort,input,cached:Math.floor(input/2),output,reasoning:Math.floor(output/2),total:input+output,...extra});
const efforts=[
 usage('shared','gpt-6','medium',100,20),
 usage('shared','gpt-6','ultra',200,40),
 usage('shared','gpt-6','ultra',20,4),
 usage('shared','other','max',40,8),
 usage('second','gpt-6','ultra',300,60),
 usage('monitor','gpt-6','ultra',10,2),
 usage('internal','gpt-6','ultra',30,6,{internal:true}),
 usage('old','gpt-6',undefined,50,10),
 usage('unknown','gpt-6','unknown',5,1),
 usage('blank','gpt-6','',5,1)
];
const none={model:'',effort:'',excludeMonitor:false,excludeInternal:false,task:null};
assert.deepEqual(M.filter(efforts,none,'monitor'),efforts);
assert.equal(M.filter(efforts,{...none,model:'gpt-6',effort:'medium'},'monitor').length,1);
assert.equal(M.sum(M.filter(efforts,{...none,model:'gpt-6',effort:'ultra',excludeMonitor:true,excludeInternal:true},'monitor')).total,624);
assert.equal(M.sum(M.filter(efforts,{...none,model:'gpt-6',effort:'ultra',task:'shared',excludeMonitor:true,excludeInternal:true},'monitor')).total,264);
assert.equal(M.filter(efforts,{...none,model:'other',effort:'ultra'},'monitor').length,0);
assert.equal(M.filter(efforts,{...none,effort:'unknown'},'monitor').length,3);
assert.equal(M.filter(efforts,{...none,effort:'max'},'monitor').length,1);
assert.equal(M.filter(efforts,{...none,effort:'ultra'},'monitor').length,5);
assert.equal(M.effortLabel('medium'),'中');
assert.equal(M.effortLabel('ultra'),'Ultra');
assert.equal(M.effortLabel('max'),'Max');
assert.equal(M.effortLabel(M.effort({})),'未记录');
assert.equal(M.effortLabel('future-effort'),'future-effort');
assert.equal(M.effortLabel('constructor'),'constructor');
assert.equal(M.effort({effort:' Ultra '}),'ultra');

const merged=M.conversations(efforts),shared=merged.find(t=>t.id==='shared');
assert.equal(shared.total,432);
assert.deepEqual(shared.modelEfforts.map(M.modelEffortLabel).sort(),['gpt-6 · Ultra','gpt-6 · 中','other · Max'].sort());
assert.equal(shared.modelEfforts.length,3);
assert(!shared.modelEfforts.some(p=>p.model==='other'&&p.effort==='ultra'));
assert.deepEqual(M.sum(merged),M.sum(efforts));
const groups=M.byModelEffort(efforts);
assert.equal(groups.length,4);
assert.equal(groups.find(g=>g.model==='gpt-6'&&g.effort==='ultra').count,4);
assert.equal(groups.find(g=>g.model==='gpt-6'&&g.effort==='ultra').total,672);
assert.equal(groups.find(g=>g.effort==='unknown').count,3);
assert.deepEqual(M.sum(groups),M.sum(efforts));
assert.deepEqual(M.sum(M.byModelEffort(M.filter(efforts,{...none,task:'shared'}))),M.sum(M.filter(efforts,{...none,task:'shared'})));
assert.equal(M.byModelEffort([]).length,0);
assert.equal(M.byModelEffort(tasks).every(g=>g.effort==='unknown'),true);
assert.equal(M.sum(M.filter(tasks,{...none,effort:'unknown'})).total,M.sum(tasks).total);
assert.equal(M.byModelEffort([usage('x','a|b','c',1,1),usage('y','a','b|c',2,2)]).length,2);

const multi=Array.from({length:12},(_,i)=>[usage('multi'+i,'gpt-6','medium',10+i,2),usage('multi'+i,'gpt-6','ultra',20+i,3)]).flat();
for(const selected of [multi,M.filter(multi,{...none,effort:'ultra'})]){
 const breakdown=M.breakdown(selected);
 assert.equal(breakdown.all.length,12);
 assert.equal(breakdown.top.length,8);
 assert.equal(breakdown.otherCount,4);
 assert.equal(breakdown.total,breakdown.top.reduce((total,t)=>total+t.total,0)+breakdown.other);
 assert.deepEqual(M.sum(breakdown.all),M.sum(selected));
 assert.deepEqual(M.sum(M.byModelEffort(selected)),M.sum(selected));
}
console.log('Reasoning-effort filters, paired conversation labels, comparison totals, old snapshots and top-eight conservation: OK');

// Fixed vertical density: 10M always occupies four equally spaced 2.5M cells.
for(const peak of [0,1,10000000]){
 const scale=M.usageScale(peak);
 assert.equal(scale.max,10000000);
 assert.equal(scale.steps,4);
 assert.equal(scale.height,300);
}
const standard=M.usageScale(10000000),double=M.usageScale(20000000),above=M.usageScale(10000001);
assert.equal(double.max,20000000);
assert.equal(double.steps,8);
assert.equal(double.height-70,2*(standard.height-70));
assert.equal(above.max,12500000);
assert.equal(above.steps,5);
for(const peak of [2500000,10000000,10000001,25000000,100000000]){
 const scale=M.usageScale(peak);
 assert(scale.max>=peak);
 assert.equal((scale.height-70)/scale.max,230/10000000);
 assert.equal(scale.max/scale.steps,2500000);
}
console.log('Fixed 2.5M tick size, 10M minimum and invariant pixels per Token: OK');

// Inputs use the dashboard timezone, independent of the browser's timezone.
const customStart=Date.UTC(2026,8,15,16,30),customEnd=Date.UTC(2026,8,17,6,0);
assert.equal(M.localDateTime(customStart,480),'2026-09-16T00:30');
assert.equal(M.parseLocalDateTime('2026-09-16T00:30',480),customStart);
assert.equal(M.localDateTime(customStart,-420),'2026-09-15T09:30');
assert.equal(M.parseLocalDateTime('2026-09-15T09:30',-420),customStart);
assert.equal(M.parseLocalDateTime('2026-01-01T00:30',480),Date.UTC(2025,11,31,16,30));
assert.equal(M.parseLocalDateTime('2024-02-29T12:00',330),Date.UTC(2024,1,29,6,30));
assert.equal(M.parseLocalDateTime('1969-12-31T17:00',-420),0);
for(const value of ['', '2026-02-29T12:00','2026-04-31T00:00','2026-13-01T00:00','2026-09-16T24:00','2026-09-16T12:60','2026-09-16','not a date'])assert(Number.isNaN(M.parseLocalDateTime(value,480)),value);
assert.equal(M.rangeError(customStart,customEnd,customEnd),'');
assert(M.rangeError(NaN,customEnd,customEnd));
assert(M.rangeError(customEnd,customEnd,customEnd));
assert(M.rangeError(customEnd,customStart,customEnd));
assert(M.rangeError(-1,customEnd,customEnd));
assert.equal(M.rangeError(customEnd-366*86400000,customEnd,customEnd),'');
assert(M.rangeError(customEnd-366*86400000-1,customEnd,customEnd));
assert.equal(M.rangeError(customStart,customEnd+60000,customEnd),'');
assert(M.rangeError(customStart,customEnd+60001,customEnd));
console.log('Custom range timezone conversion, calendar validation, ordering and 366-day limit: OK');

const accountRows=[{id:'same',model:'m',effort:'medium',account:'A',total:100},{id:'same',model:'m',effort:'medium',account:'B',total:200},{id:'old',model:'m',total:30}];
assert.equal(M.sum(M.filter(accountRows,{account:'A'},'')).total,100);
assert.equal(M.sum(M.filter(accountRows,{account:'B'},'')).total,200);
assert.equal(M.sum(M.filter(accountRows,{account:'__unknown__'},'')).total,30);
assert.equal(M.sum(M.filter(accountRows,{account:''},'')).total,330);
console.log('Account filters preserve totals and treat older snapshots as unknown: OK');
