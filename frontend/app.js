'use strict';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const h = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (v, digits=0) => Number(v || 0).toLocaleString('zh-CN', {maximumFractionDigits:digits});
const titles = {overview:'经营总览',agent:'智能助手',business:'生产与经营',reports:'报表工作室',skills:'技能与流程'};
const state = {page:'overview',bootstrap:null,session:null,busy:false,polling:false,run:null,report:null,charts:[]};
const statusNames = {confirmed:'待排产',in_production:'生产中',partial_shipped:'部分发货',shipped:'已发货',planned:'待开工',running:'生产中',completed:'已完工',available:'可用',maintenance:'维护中',ordered:'待收货',received:'已入库'};
const columnNames = {id:'编号',name:'名称',customer:'客户',customer_id:'客户编号',product:'产品',product_id:'产品编号',quantity:'数量',unit_price:'单价 / 元',due_date:'交货日期',status:'状态',shipped:'已发货 / m',created_at:'创建时间',machine:'设备',machine_id:'设备编号',order_id:'销售单号',work_order_id:'工单号',good_qty:'合格 / m',bad_qty:'不合格 / m',unit:'单位',stock:'库存',safety_stock:'安全库存',unit_cost:'成本单价',supplier_id:'供应商',material_id:'原料编号',spec:'规格',price:'售价 / 元',workshop:'车间',defect:'缺陷',item_type:'类型',item_id:'物料编号',reason:'原因',reference_id:'关联单号',operation:'操作',request_id:'请求标识',payload:'参数',result:'执行结果',shortage:'缺口',contact:'联系人'};
const chartTypes = {table:'明细表',pivot:'透视表',bar:'柱状图',line:'折线图',area:'面积图',pie:'饼图',scatter:'散点图',heatmap:'热力图'};

async function api(path, options={}) {
  const response = await fetch('/api'+path, {...options,headers:{'Content-Type':'application/json','X-Demo-Token':state.bootstrap?.token || '',...options.headers}});
  let data; try { data = await response.json(); } catch { throw new Error('服务响应异常，请确认Demo仍在运行'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
const post = (path, body) => api(path,{method:'POST',body:JSON.stringify(body)});
function toast(text) { const node=$('#toast'); node.textContent=text;node.style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.style.display='none',4000); }
function errorBox(error) { return `<div class="error">${h(error.message || error)}</div>`; }
function heading(eyebrow,title,subtitle,actions='') { return `<div class="page-heading"><div><div class="eyebrow">${h(eyebrow)}</div><h1>${h(title)}</h1><p class="subtitle">${h(subtitle)}</p></div><div class="actions">${actions}</div></div>`; }
function disposeCharts() { state.charts.forEach(c=>c.dispose());state.charts=[]; }
function chart(node,option) { if(!node) return; const previous=echarts.getInstanceByDom(node);if(previous)previous.dispose();const instance=echarts.init(node);instance.setOption(option);state.charts.push(instance);return instance; }
window.addEventListener('resize',()=>state.charts.filter(c=>!c.isDisposed()).forEach(c=>c.resize()));
function statusTag(value) { const kind=['planned','ordered','maintenance'].includes(value)?'warn':['shipped','completed','received'].includes(value)?'gray':'';return `<span class="tag ${kind}">${h(statusNames[value] || value)}</span>`; }
function table(data, columns, labels=true) {
  if(!data.length) return '<div class="empty">暂无数据</div>';
  columns=columns || Object.keys(data[0]);
  return `<div class="table-wrap"><table><thead><tr>${columns.map(c=>`<th>${h(labels ? columnNames[c] || c : c)}</th>`).join('')}</tr></thead><tbody>${data.map(row=>`<tr>${columns.map(c=>`<td>${c==='status'?statusTag(row[c]):h(typeof row[c]==='number'?number(row[c],4):typeof row[c]==='object'&&row[c]!==null?JSON.stringify(row[c]):String(row[c]??'—'))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function modal(title,body) { $('#modal-body').innerHTML=`<div class="modal-head"><h2>${h(title)}</h2><button class="close" aria-label="关闭">×</button></div>${body}`;$('#modal .close').onclick=()=>$('#modal').close();$('#modal').showModal(); }
function setAgentPrompt(text) { state.pendingPrompt=text; navigate('agent'); }
function bindAgentButtons() { $$('[data-prompt]').forEach(b=>b.onclick=()=>setAgentPrompt(b.dataset.prompt)); }

async function navigate(page) {
  if(!titles[page]) page='overview';
  state.page=page;location.hash=page;disposeCharts();
  $$('nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===page));$('#page-title').textContent=titles[page];
  $('#page').innerHTML='<div class="loading">正在加载…</div>';
  try { await ({overview:overview,agent:agentPage,business:businessPage,reports:reportsPage,skills:skillsPage})[page](); }
  catch(error) { if(state.page===page) $('#page').innerHTML=errorBox(error)+ '<button id="retry" class="mt">重新加载</button>'; if($('#retry'))$('#retry').onclick=()=>navigate(page); }
}
$$('nav button').forEach(b=>b.onclick=()=>navigate(b.dataset.page));
$('.brand').onclick=e=>{e.preventDefault();navigate('overview');};

async function overview() {
  const data=await api('/dashboard');if(state.page!=='overview')return;
  const k=data.kpi.rows[0], low=data.materials.rows.filter(r=>r.shortage>0);
  $('#page').innerHTML=heading('FACTORY OVERVIEW','让每一米面料，都有迹可循。','连接订单、库存与生产，掌握工厂此刻的运转。',`<button id="refresh">↻ 刷新数据</button><button class="primary" data-prompt="请使用生产经营晨报技能，检查交期、缺料和质量，并生成异常明细表和产品订单金额柱状图。">✳ 生成经营晨报</button>`)+
  `<div class="kpi-grid">
  <div class="kpi"><div class="kpi-label">订单总金额 <span class="kpi-icon">¥</span></div><div class="kpi-value">${number(k.order_value/10000,2)}<small>万元</small></div><div class="kpi-foot">所有订单金额 · 非回款口径</div></div>
  <div class="kpi"><div class="kpi-label">待交付订单 <span class="kpi-icon">▤</span></div><div class="kpi-value">${k.open_orders}<small>单</small></div><div class="kpi-foot"><b>产销协同</b> · 未完成发货的订单</div></div>
  <div class="kpi"><div class="kpi-label">生产中工单 <span class="kpi-icon">⚒</span></div><div class="kpi-value">${k.running_work_orders}<small>张</small></div><div class="kpi-foot">已领料并进入生产的工单</div></div>
  <div class="kpi"><div class="kpi-label">综合良品率 <span class="kpi-icon">✓</span></div><div class="kpi-value">${number(k.yield_rate,2)}<small>%</small></div><div class="kpi-foot">累计合格米数 / 累计报工米数</div></div></div>
  <div class="dashboard-grid"><section class="card"><div class="card-head"><h2>订单金额趋势</h2><small>按下单月份 · 元</small></div><div class="card-body"><div id="sales-chart" class="chart"></div></div></section>
  <section class="card"><div class="card-head"><h2>原料库存关注</h2><span class="badge-count">${low.length} 项低于安全线</span></div>${data.materials.rows.map(r=>`<div class="inventory-item"><div class="line"><span>${h(r.name)}</span><span>${number(r.stock)} <small>${r.unit}</small></span></div><div class="track ${r.shortage?'warn':''}"><div style="width:${Math.min(r.stock/r.safety_stock*70,100)}%"></div></div><div class="line" style="margin:8px 0 0"><small>安全库存 ${number(r.safety_stock)} ${r.unit}</small><small>${r.shortage?'缺口 '+number(r.shortage)+' '+r.unit:'库存充足'}</small></div></div>`).join('')}</section></div>
  <div class="insight"><span class="spark">✳</span><p><strong>${low.length ? `${low.length} 种原料需要关注补货` : '原料库存处于安全范围'}</strong>${low.map(r=>h(r.name)+' 缺口 '+number(r.shortage)+' '+r.unit).join('；') || '可进一步结合待生产订单的BOM核算物料需求。'}</p><button data-prompt="请结合待生产订单、BOM和库存分析原料缺口，生成补料建议表，暂不创建采购单。">让助手分析 ↗</button></div>
  <div class="dashboard-grid"><section class="card"><div class="card-head"><h2>近期销售订单</h2><button class="soft" id="goto-orders">查看全部 ↗</button></div>${table(data.recent_orders.rows,['id','customer','product','quantity','due_date','status'])}</section>
  <section class="card"><div class="card-head"><h2>车间工单</h2><small>最近 8 张</small></div>${table(data.work_orders.rows,['id','machine','quantity','status'])}</section></div><div class="footer-note"><span>织序 · 纺织生产经营一体化</span><span>模拟业务数据 / 数据更新于 ${h(data.kpi.as_of.slice(11,19))}</span></div>`;
  const months=[...new Set(data.sales.rows.map(r=>r.month))],products=[...new Set(data.sales.rows.map(r=>r.product))];
  chart($('#sales-chart'),{color:['#538774','#a4ba86','#dbca9d'],tooltip:{trigger:'axis'},legend:{bottom:0,icon:'circle',itemWidth:7,textStyle:{fontSize:10,color:'#809481'}},grid:{left:45,right:12,top:15,bottom:60},xAxis:{type:'category',data:months,axisLine:{lineStyle:{color:'#e5ece1'}},axisTick:{show:false},axisLabel:{fontSize:10,color:'#93a18d'}},yAxis:{type:'value',splitLine:{lineStyle:{color:'#eff3eb',type:'dashed'}},axisLabel:{fontSize:10,color:'#93a18d',formatter:v=>v/10000+'万'}},series:products.map(name=>({name,type:'bar',barMaxWidth:24,itemStyle:{borderRadius:[4,4,0,0]},data:months.map(m=>data.sales.rows.find(r=>r.month===m&&r.product===name)?.amount || 0)}))});
  $('#refresh').onclick=()=>navigate('overview');$('#goto-orders').onclick=()=>navigate('business');bindAgentButtons();
}

const entities={orders:'销售订单',work_orders:'生产工单',materials:'原料库存',products:'成品库存',purchases:'采购管理',production_reports:'报工质检',machines:'设备',shipments:'发货',stock_movements:'库存流水',bom:'物料清单',customers:'客户',suppliers:'供应商',audit:'操作审计'};
let entity='orders';
async function businessPage() {
  if(state.page!=='business')return;
  $('#page').innerHTML=heading('ERP + MES','生产与经营','从接单到交付，所有业务记录在同一套系统中。',`<button id="business-refresh">↻ 刷新</button><button class="primary" id="new-command">＋ 办理业务</button>`)+`<div class="tabs">${Object.entries(entities).map(([k,v])=>`<button data-entity="${k}" class="${entity===k?'selected':''}">${v}</button>`).join('')}</div><section class="card"><div class="table-toolbar"><h2>${entities[entity]}</h2><input id="data-search" aria-label="搜索当前表格" placeholder="搜索当前表格…"></div><div id="entity-data" class="loading">读取数据…</div></section><p class="note mt">数量按物料单位记录；销售、生产和发货数量均为米。业务操作自动记录审计日志。</p>`;
  $$('[data-entity]').forEach(b=>b.onclick=()=>{entity=b.dataset.entity;businessPage();});$('#new-command').onclick=()=>businessModal();$('#business-refresh').onclick=businessPage;
  const current=entity;
  const result=await post('/query',{sql:`SELECT * FROM ${entity} ORDER BY ${['bom'].includes(entity)?'product_id':'id'} DESC LIMIT 500`});
  if(state.page!=='business'||entity!==current)return;
  $('#entity-data').className='';$('#entity-data').innerHTML=table(result.rows);
  $('#data-search').oninput=e=>{$('#entity-data').innerHTML=table(result.rows.filter(r=>JSON.stringify(r).toLowerCase().includes(e.target.value.toLowerCase())));};
}

async function businessModal() {
  modal('办理业务',`<div class="field"><label>业务操作</label><select id="command-kind">${Object.entries(state.bootstrap.commands).map(([k,v])=>`<option value="${k}">${h(v.description.split('，')[0])}</option>`).join('')}</select></div><form id="business-form" class="mt"><div id="command-fields" class="form-grid"></div><div class="actions mt"><button type="submit" class="primary">提交业务</button></div><div id="command-result" class="mt"></div></form>`);
  const lookups={};
  await Promise.all(['customers','products','materials','machines','orders','work_orders','purchases'].map(async name=>{lookups[name]=(await post('/query',{sql:`SELECT * FROM ${name} ORDER BY id DESC LIMIT 500`})).rows;}));
  const lookupKeys={customer_id:'customers',product_id:'products',material_id:'materials',machine_id:'machines',order_id:'orders',work_order_id:'work_orders',purchase_id:'purchases'};
  let operationKey=crypto.randomUUID();
  function fields() {
    operationKey=crypto.randomUUID();$('#command-result').innerHTML='';
    const schema=state.bootstrap.commands[$('#command-kind').value].schema;
    $('#command-fields').innerHTML=Object.entries(schema.properties).map(([key,spec])=>{
      const required=(schema.required || []).includes(key),numeric=spec.type==='number'||spec.anyOf?.some(x=>x.type==='number');
      const options=lookups[lookupKeys[key]];
      const input=options?`<select name="${key}" ${required?'required':''}><option value="">请选择</option>${options.map(r=>`<option value="${h(r.id)}">${h(r.id+' · '+(r.name || r.status || '')+(r.quantity?' · '+r.quantity:''))}</option>`).join('')}</select>`:`<input name="${key}" type="${key==='due_date'?'date':numeric?'number':'text'}" ${numeric?'step="any" min="0"':''} ${required?'required':''} ${spec.default!==undefined?`value="${h(spec.default)}"`:''} placeholder="${key==='quantity'&&!required?'留空自动计算未排产数量':''}">`;
      return `<div class="field"><label>${h(columnNames[key] || key)} ${required?'*':''}</label>${input}</div>`;
    }).join('');
  }
  $('#command-kind').onchange=fields;fields();
  $('#business-form').oninput=()=>{operationKey=crypto.randomUUID();};
  $('#business-form').onsubmit=async e=>{
    e.preventDefault();const button=$('button[type=submit]',e.target);button.disabled=true;
    try { const schema=state.bootstrap.commands[$('#command-kind').value].schema,params={};
      for(const [key,value] of new FormData(e.target).entries()){if(value==='')continue;const spec=schema.properties[key];params[key]=(spec.type==='number'||spec.anyOf?.some(x=>x.type==='number'))?Number(value):value;}
      const result=await post('/business/'+$('#command-kind').value,{params,request_id:operationKey});
      $('#command-result').innerHTML=`<div class="success">业务已成功提交</div><pre class="json-result">${h(JSON.stringify(result,null,2))}</pre>`;toast('业务数据已更新');businessPage();
    } catch(error){$('#command-result').innerHTML=errorBox(error);} finally{button.disabled=false;}
  };
}

async function agentPage() {
  const sessions=await api('/sessions');if(state.page!=='agent')return;
  $('#page').innerHTML=heading('AI WORKSPACE','把业务交给一句话。','查询、分析、执行业务。每一步都有真实数据与执行记录。',`<span class="tag">${h(state.bootstrap.model)}</span>`)+`<div class="chat-layout"><aside class="card chat-history"><button id="new-chat">＋ 新建对话</button><div class="session-list">${sessions.map(s=>`<button class="session-item ${state.session===s.id?'active':''}" data-session="${h(s.id)}">${h(s.title)}<small style="display:block">${h(s.created_at.slice(5,16).replace('T',' '))}</small></button>`).join('') || '<p class="note mt">对话会自动保存在本机</p>'}</div></aside><section class="card chat-main"><div id="chat-messages" class="chat-messages"></div><form class="chat-composer" id="chat-form"><textarea id="chat-input" aria-label="发送给智能助手的消息" placeholder="例如：查询待交付订单，分析缺料并画一张柱状图…" required></textarea><div class="composer-foot"><span id="chat-status">${state.busy?'正在处理，请稍候…':'Enter 发送 · Shift + Enter 换行'}</span><button class="primary" id="chat-send" ${state.busy?'disabled':''}>发送 ↗</button></div></form></section><aside class="card trace-panel"><div class="trace-title">执行记录 <span class="badge-count">TOOLS</span></div><div id="trace-list" class="trace-list"><p class="note">模型每次查询、业务操作和报表生成都会记录在这里。</p></div></aside></div>`;
  $('#new-chat').onclick=()=>{if(state.busy)return toast('当前任务完成后可新建对话');state.session=null;state.run=null;agentPage();};
  $$('[data-session]').forEach(b=>b.onclick=()=>{if(state.busy)return toast('当前任务完成后可切换对话');state.session=b.dataset.session;state.run=null;agentPage();});
  $('#chat-form').onsubmit=sendChat;
  $('#chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!state.busy)$('#chat-form').requestSubmit();}};
  await loadChat();
  if(state.pendingPrompt){$('#chat-input').value=state.pendingPrompt;state.pendingPrompt=null;$('#chat-input').focus();}
}
function messageHtml(role,text){return `<div class="message ${h(role)}"><div class="message-label">${role==='user'?'○ 你':'✳ 织序助手'}</div><div class="message-content">${h(text)}</div></div>`;}
async function loadChat(){
  if(state.page!=='agent')return;
  if(!state.session){$('#chat-messages').innerHTML=`<div class="chat-welcome"><span class="spark">✳</span><h2>今天，想从哪里开始？</h2><p class="subtitle">我可以帮你看清经营情况，也可以直接办理业务。</p><div class="suggestions"><button data-prompt="分析各产品销售订单金额与生产良品率，生成柱状图和明细表。">◷ 分析产品表现，并绘制报表 ↗</button><button data-prompt="请使用生产经营晨报技能，检查交期、缺料和质量。">☀ 生成今天的生产经营晨报 ↗</button><button data-prompt="查询所有原料的安全库存缺口，生成补货建议表，暂不采购。">▦ 检查原料缺口，制定补料建议 ↗</button><button data-prompt="请查看可用客户、产品和空闲设备，告诉我接单即排产流程需要哪些参数。">⌘ 用技能自动完成接单与排产 ↗</button></div></div>`;$$('#chat-messages [data-prompt]').forEach(b=>b.onclick=()=>{$('#chat-input').value=b.dataset.prompt;$('#chat-input').focus();});return;}
  const session=await api('/sessions/'+state.session);if(state.page!=='agent')return;
  $('#chat-messages').innerHTML=session.messages.filter(m=>['user','assistant'].includes(m.role)&&m.body.content).map(m=>messageHtml(m.role,m.body.content)).join('');
  const last=session.runs.at(-1);if(last){state.run=last.id;const run=await api('/runs/'+last.id);if(state.page!=='agent')return;$('#trace-list').innerHTML='';run.events.forEach(renderEvent);if(last.status==='running'&&!state.polling){state.busy=true;pollRun(last.id);}else if(last.status==='interrupted'){$('#trace-list').innerHTML+=errorBox('上次执行因服务重启中断，请核对业务记录后继续。');}}
  $('#chat-messages').scrollTop=$('#chat-messages').scrollHeight;
}
async function sendChat(e){
  e.preventDefault();if(state.busy)return;const text=$('#chat-input').value.trim();if(!text)return;
  state.busy=true;$('#chat-send').disabled=true;$('#chat-input').value='';$('#chat-status').textContent='正在提交任务…';
  try{const result=await post('/chat',{message:text,session_id:state.session});state.session=result.session_id;state.run=result.run_id;await agentPage();if(!state.polling)pollRun(result.run_id);}
  catch(error){state.busy=false;toast(error.message);if($('#chat-send'))$('#chat-send').disabled=false;if($('#chat-input'))$('#chat-input').value=text;}
}
function renderEvent(e){
  const parent=$('#trace-list');if(!parent||parent.querySelector(`[data-event="${e.id}"]`))return;
  const p=e.payload;
  if(e.kind==='tool_start')parent.insertAdjacentHTML('beforeend',`<details class="trace-event" data-event="${e.id}"><summary>↗ ${h(p.name)}</summary><pre>${h(JSON.stringify(p.arguments,null,2))}</pre></details>`);
  if(e.kind==='tool_result'){
    parent.insertAdjacentHTML('beforeend',`<details class="trace-event ${p.ok?'':'fail'}" data-event="${e.id}"><summary>${p.ok?'✓':'!'} ${h(p.name)} ${p.ok?'完成':'未成功'}</summary><pre>${h(JSON.stringify(p.result || p.error,null,2))}</pre></details>`);
    if(p.ok&&p.name==='create_report') {const b=document.createElement('button');b.className='artifact-link';b.textContent='◷ '+p.result.title;b.onclick=()=>{state.report=p.result.id;navigate('reports');};parent.appendChild(b);}
  }
  if(e.kind==='status') {parent.insertAdjacentHTML('beforeend',`<div class="trace-status" data-event="${e.id}">${h(p.message)}</div>`);if($('#chat-status'))$('#chat-status').textContent=p.message;}
  if(e.kind==='error')parent.insertAdjacentHTML('beforeend',`<div class="error" data-event="${e.id}">${h(p.message)}</div>`);
  parent.scrollTop=parent.scrollHeight;
}
async function pollRun(id){
  if(state.polling)return;state.polling=true;let after=0;
  try{while(true){const run=await api('/runs/'+id+'?after='+after);for(const e of run.events){after=e.id;if(state.page==='agent'&&state.run===id)renderEvent(e);}
    if(run.status!=='running'){state.busy=false;if(state.page==='agent'){await loadChat();if($('#chat-send'))$('#chat-send').disabled=false;if($('#chat-status'))$('#chat-status').textContent=`${run.status==='completed'?'已完成':'未完成'} · 模型调用 ${run.usage.model_calls||0} 次 · ${number((run.usage.prompt_tokens||0)+(run.usage.completion_tokens||0))} tokens`;}else toast(run.status==='completed'?'助手任务已完成':'助手任务未完成，请查看执行记录');break;}
    await new Promise(resolve=>setTimeout(resolve,1200));
  }}catch(error){state.busy=false;toast('连接中断：'+error.message);if($('#chat-send'))$('#chat-send').disabled=false;}finally{state.polling=false;}
}

let reportDraft={title:'产品订单金额',chart_type:'bar',sql:'SELECT p.name AS 产品, ROUND(SUM(o.quantity*o.unit_price),2) AS 订单金额 FROM orders o JOIN products p ON p.id=o.product_id GROUP BY p.id,p.name ORDER BY 订单金额 DESC',rows:[],x:'',y:[],group:'',description:''};
let reportColumns=[];
async function reportsPage(){
  const reports=await api('/reports');if(state.page!=='reports')return;
  if(state.report){const saved=await api('/reports/'+state.report);reportDraft={...saved,rows:saved.data.rows.map(r=>({...r}))};reportColumns=[...saved.data.columns];}
  $('#page').innerHTML=heading('REPORT STUDIO','让数据，呈现更多可能。','AI生成报表，也可以在线编辑数据、切换图形，保存与导出。',`<button class="primary" id="new-report">＋ 新建报表</button>`)+`<div class="report-layout"><aside class="card report-list"><h2>已保存的报表 <span class="badge-count">${reports.length}</span></h2>${reports.map(r=>`<button class="report-item ${r.id===state.report?'active':''}" data-report="${r.id}">${h(r.title)}<small>${h(chartTypes[r.chart_type])} · ${h(r.created_at.slice(5,16).replace('T',' '))}</small></button>`).join('') || '<p class="note mt">向助手提出报表需求，或在右侧绘制第一张报表。</p>'}</aside><section class="card"><div class="card-body"><div class="form-grid"><div class="field"><label>报表名称</label><input id="report-title" value="${h(reportDraft.title)}"></div><div class="field"><label>展示类型</label><select id="report-type">${Object.entries(chartTypes).map(([k,v])=>`<option value="${k}" ${k===reportDraft.chart_type?'selected':''}>${v}</option>`).join('')}</select></div></div><div class="field mt"><label>数据说明 / 分析口径</label><input id="report-description" value="${h(reportDraft.description)}" placeholder="例如：订单金额按下单日期统计，不代表实收"></div><details class="mt" ${reportDraft.rows.length?'':'open'}><summary class="note">SQL 数据源（只读）</summary><textarea id="report-sql" class="code code-editor" aria-label="只读SQL查询">${h(reportDraft.sql)}</textarea><button id="run-query" class="mt">↻ 查询数据</button></details><div class="editor-grid mt" id="chart-fields"></div><div class="editor-table" id="editable-data"></div><div class="actions mt"><button id="add-row">＋ 行</button><button id="add-column">＋ 列</button><button id="import-json">导入 JSON</button><button id="preview-chart" class="soft">预览图表</button><button id="save-report" class="primary">保存报表</button><button id="export-csv">导出 CSV</button><button id="export-png">导出 PNG</button></div><div id="report-error" class="mt"></div><div class="report-preview"><h2 id="preview-title">${h(reportDraft.title)}</h2><div id="report-chart"></div><div id="report-table"></div><div class="report-meta"><span id="report-source">${h(reportDraft.data?.source || '查询数据后可开始绘图')}</span><span>${h(reportDraft.data?.as_of || '')}</span></div></div></div></section></div>`;
  $$('[data-report]').forEach(b=>b.onclick=()=>{state.report=b.dataset.report;reportsPage();});
  $('#new-report').onclick=()=>{state.report=null;reportDraft={title:'新建报表',chart_type:'table',rows:[{'项目':'样例 A','数值':10},{'项目':'样例 B','数值':20}],sql:'',x:'项目',y:['数值'],group:'',description:''};reportColumns=['项目','数值'];reportsPage();};
  $('#run-query').onclick=async()=>{try{const data=await post('/query',{sql:$('#report-sql').value});reportDraft.sql=$('#report-sql').value;reportDraft.rows=data.rows;reportDraft.data=data;reportColumns=data.columns;$('#report-source').textContent=data.source+(data.truncated?' · 结果已截断至500行':'');renderGrid();renderChartFields();previewReport();}catch(error){$('#report-error').innerHTML=errorBox(error);}};
  $('#report-type').onchange=()=>{readDraft();renderChartFields();previewReport();};
  $('#add-row').onclick=()=>{if(reportDraft.rows.length>=500)return toast('最多500行');if(!reportColumns.length)reportColumns=['项目','数值'];reportDraft.rows.push(Object.fromEntries(reportColumns.map((c,i)=>[c,i===0?'新项目':0])));manualData();renderGrid();renderChartFields();};
  $('#add-column').onclick=()=>{const name=prompt('新列名称');if(!name)return;if(reportColumns.includes(name))return toast('列名已存在');if(reportColumns.length>=50)return toast('最多50列');reportColumns.push(name);reportDraft.rows.forEach(r=>r[name]=0);manualData();renderGrid();renderChartFields();};
  $('#import-json').onclick=()=>{modal('导入表格数据',`<p class="note">输入对象数组，每行使用相同列名。例如 [{"产品":"府绸","数量":100}]</p><textarea id="json-import" class="code code-editor">${h(JSON.stringify(reportDraft.rows,null,2))}</textarea><button id="json-import-confirm" class="primary mt">导入</button><div id="json-import-error" class="mt"></div>`);$('#json-import-confirm').onclick=()=>{try{const data=JSON.parse($('#json-import').value);if(!Array.isArray(data)||!data.length||data.length>500||data.some(r=>!r||Array.isArray(r)||typeof r!=='object'))throw new Error('需要1至500行对象数组');const cols=Object.keys(data[0]);if(!cols.length||cols.length>50||data.some(r=>Object.keys(r).length!==cols.length||cols.some(c=>!(c in r))||Object.values(r).some(v=>v!==null&&typeof v==='object')))throw new Error('列名必须一致，单元格只能是数字、文本、布尔值或null');reportDraft.rows=data;reportColumns=cols;manualData();renderGrid();renderChartFields();previewReport();$('#modal').close();}catch(error){$('#json-import-error').innerHTML=errorBox(error);}};};
  $('#preview-chart').onclick=previewReport;
  $('#save-report').onclick=async()=>{const button=$('#save-report');button.disabled=true;try{readDraft();const payload={title:reportDraft.title,chart_type:reportDraft.chart_type,sql:reportDraft.sql,rows:reportDraft.sql?[]:reportDraft.rows,x:reportDraft.x,y:reportDraft.y,group:reportDraft.group,description:reportDraft.description};const result=await post('/reports',payload);state.report=result.id;toast('报表快照已保存');await reportsPage();}catch(error){$('#report-error').innerHTML=errorBox(error);}finally{if($('#save-report'))$('#save-report').disabled=false;}};
  $('#export-csv').onclick=()=>{readDraft();const safe=v=>{let s=String(v??'');if(/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};const text='\ufeff'+[reportColumns.map(safe).join(','),...reportDraft.rows.map(r=>reportColumns.map(c=>safe(r[c])).join(','))].join('\r\n');download(new Blob([text],{type:'text/csv;charset=utf-8'}),reportDraft.title+'.csv');};
  $('#export-png').onclick=()=>{const instance=echarts.getInstanceByDom($('#report-chart'));if(!instance)return toast('请先预览图形；表格可导出CSV');const a=document.createElement('a');a.href=instance.getDataURL({type:'png',pixelRatio:2,backgroundColor:'#fff'});a.download=reportDraft.title+'.png';a.click();};
  renderGrid();renderChartFields();if(reportDraft.rows.length)previewReport();
}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function manualData(){reportDraft.sql='';if($('#report-sql'))$('#report-sql').value='';if($('#report-source'))$('#report-source').textContent='手工编辑数据（已断开原SQL，保存当前编辑内容）';}
function renderGrid(){
  $('#editable-data').innerHTML=reportColumns.length?`<table><thead><tr>${reportColumns.map(c=>`<th>${h(c)}</th>`).join('')}<th>操作</th></tr></thead><tbody>${reportDraft.rows.map((row,i)=>`<tr>${reportColumns.map((c,j)=>`<td><input aria-label="第${i+1}行 ${h(c)}" data-row="${i}" data-col="${j}" value="${h(row[c])}"></td>`).join('')}<td><button data-remove-row="${i}">删除</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty">执行查询，或添加列和数据行开始绘图</div>';
  $$('#editable-data input').forEach(input=>input.onchange=()=>{const value=input.value;reportDraft.rows[Number(input.dataset.row)][reportColumns[Number(input.dataset.col)]]=value.trim()!==''&&Number.isFinite(Number(value))?Number(value):value;manualData();});
  $$('[data-remove-row]').forEach(button=>button.onclick=()=>{reportDraft.rows.splice(Number(button.dataset.removeRow),1);manualData();renderGrid();});
}
function renderChartFields(){
  const numeric=reportColumns.filter(c=>reportDraft.rows.length&&reportDraft.rows.every(r=>typeof r[c]==='number'));
  if(!reportColumns.includes(reportDraft.x))reportDraft.x=reportColumns[0]||'';
  reportDraft.y=reportDraft.y.filter(y=>numeric.includes(y));if(!reportDraft.y.length&&numeric.length)reportDraft.y=[numeric[0]];
  const options=(selected)=>reportColumns.map(c=>`<option value="${h(c)}" ${selected===c?'selected':''}>${h(c)}</option>`).join('');
  $('#chart-fields').innerHTML=`<div class="field"><label>维度 / X 轴</label><select id="report-x">${options(reportDraft.x)}</select></div><div class="field"><label>数值列（Ctrl 多选）</label><select id="report-y" multiple size="3">${numeric.map(c=>`<option value="${h(c)}" ${reportDraft.y.includes(c)?'selected':''}>${h(c)}</option>`).join('')}</select></div><div class="field"><label>分组列（透视表 / 热力图）</label><select id="report-group"><option value="">请选择</option>${options(reportDraft.group)}</select></div>`;
}
function readDraft(){reportDraft.title=$('#report-title').value;reportDraft.description=$('#report-description').value;reportDraft.chart_type=$('#report-type').value;reportDraft.sql=$('#report-sql').value.trim();reportDraft.x=$('#report-x')?.value||'';reportDraft.y=$$('#report-y option:checked').map(o=>o.value);reportDraft.group=$('#report-group')?.value||'';}
function previewReport(){
  readDraft();$('#report-error').innerHTML='';$('#preview-title').textContent=reportDraft.title;
  const node=$('#report-chart'),old=echarts.getInstanceByDom(node);if(old)old.dispose();node.className='';$('#report-table').innerHTML='';
  const {rows:data,chart_type:type,x,y,group}=reportDraft;if(!data.length){$('#report-table').innerHTML='<div class="empty">没有可绘制的数据</div>';return;}
  if(type==='table'){$('#report-table').innerHTML=table(data,reportColumns,false);return;}
  if(!x||!y.length){$('#report-error').innerHTML=errorBox('请选择维度与数值列');return;}
  if(data.some(r=>y.some(c=>typeof r[c]!=='number'))){$('#report-error').innerHTML=errorBox('数值列必须全部为数字');return;}
  const colors=['#528a72','#b3c58d','#d4ae77','#8eacb9','#bc9fb6','#b8c7bd'];
  const option={color:colors,tooltip:{trigger:'axis'},legend:{bottom:0,textStyle:{fontSize:11,color:'#7b947a'}},grid:{top:25,right:30,bottom:65,left:65},xAxis:{type:'category',data:data.map(r=>r[x]),axisLabel:{fontSize:10,color:'#8fa086'},axisLine:{lineStyle:{color:'#e0e9d9'}},axisTick:{show:false}},yAxis:{type:'value',axisLabel:{fontSize:10,color:'#8fa086'},splitLine:{lineStyle:{color:'#eef3e8'}}}};
  if(type==='pivot'||type==='heatmap'){
    if(!group){$('#report-error').innerHTML=errorBox('请选择分组列');return;}
    const xs=[...new Set(data.map(r=>String(r[x])))],gs=[...new Set(data.map(r=>String(r[group])))];
    const sum=(xx,gg)=>data.filter(r=>String(r[x])===xx&&String(r[group])===gg).reduce((n,r)=>n+Number(r[y[0]]),0);
    if(type==='pivot'){const labels=['维度',...gs.map(g=>'分组 · '+g)];const records=xs.map(xx=>Object.fromEntries([['维度',xx],...gs.map(g=>['分组 · '+g,sum(xx,g)])]));$('#report-table').innerHTML=table(records,labels,false);return;}
    const values=xs.flatMap((xx,i)=>gs.map((gg,j)=>[i,j,sum(xx,gg)]));option.xAxis.data=xs;option.yAxis={type:'category',data:gs};option.tooltip={position:'top'};option.visualMap={min:Math.min(0,...values.map(v=>v[2])),max:Math.max(1,...values.map(v=>v[2])),calculable:true,orient:'horizontal',left:'center',bottom:0,inRange:{color:['#edf4df','#2e7553']}};option.series=[{name:y[0],type:'heatmap',data:values,label:{show:true},emphasis:{itemStyle:{shadowBlur:8}}}];delete option.legend;
  }else if(type==='pie'){delete option.xAxis;delete option.yAxis;option.tooltip={trigger:'item'};option.series=[{name:y[0],type:'pie',radius:['38%','67%'],center:['50%','45%'],data:data.map(r=>({name:String(r[x]),value:r[y[0]]})),label:{fontSize:11}}];}
  else if(type==='scatter'){if(data.some(r=>typeof r[x]!=='number')){$('#report-error').innerHTML=errorBox('散点图X轴也必须是数字');return;}option.xAxis={type:'value',name:x};option.tooltip={trigger:'item'};option.series=y.map(c=>({name:c,type:'scatter',symbolSize:13,data:data.map(r=>[r[x],r[c]])}));}
  else option.series=y.map(c=>({name:c,type:type==='area'?'line':type,smooth:type!=='bar',barMaxWidth:48,areaStyle:type==='area'?{opacity:.15}:undefined,itemStyle:{borderRadius:type==='bar'?[5,5,0,0]:0},data:data.map(r=>r[c])}));
  node.className='chart chart-tall';chart(node,option);
}

async function skillsPage(){
  const skills=await api('/skills');if(state.page!=='skills')return;
  $('#page').innerHTML=heading('SKILLS & WORKFLOWS','把经验，变成可复用的能力。','配置领域知识与自动化流程，让助手按工厂的方式工作。',`<button id="add-skill" class="primary">＋ 接入技能</button>`)+`<div class="skill-grid">${skills.map((s,i)=>`<section class="card skill-card"><div class="actions" style="justify-content:space-between"><div class="skill-icon">${['⌘','▦','☀'][i%3]}</div><label class="switch"><input type="checkbox" data-skill-toggle="${h(s.id)}" ${s.enabled?'checked':''}>启用</label></div><h2>${h(s.name)}</h2><p>${h(s.description)}</p><span class="note">${s.steps.length?'事务流程 · '+s.steps.length+' 个步骤':'分析指南 · 自主组合工具'} <span style="float:right">v${h(s.version)}</span></span><div class="actions"><button data-edit-skill="${h(s.id)}">配置技能</button><button class="soft" data-use-skill="${h(s.id)}" ${s.enabled?'':'disabled'}>交给助手 ↗</button></div></section>`).join('')}</div><div class="inline-note">技能可包含领域指令、输入参数和业务步骤。流程中的步骤会在同一事务内提交，失败全部回滚。启用状态和配置修改立即生效，业务规则始终由系统后端校验。</div>`;
  $$('[data-skill-toggle]').forEach(input=>input.onchange=async()=>{const skill=skills.find(s=>s.id===input.dataset.skillToggle);try{await api('/skills/'+skill.id,{method:'PUT',body:JSON.stringify({...skill,enabled:input.checked})});toast(input.checked?'技能已启用':'技能已禁用');skillsPage();}catch(error){input.checked=!input.checked;toast(error.message);}});
  $$('[data-edit-skill]').forEach(b=>b.onclick=()=>skillModal(skills.find(s=>s.id===b.dataset.editSkill)));
  $$('[data-use-skill]').forEach(b=>b.onclick=()=>{const skill=skills.find(s=>s.id===b.dataset.useSkill);setAgentPrompt(`请使用“${skill.name}”技能（${skill.id}）。${skill.steps.length?'先读取技能并告诉我需要补充哪些业务参数。':'执行检查并生成相应报表。'}`);});
  $('#add-skill').onclick=()=>skillModal({id:'custom-review',name:'自定义经营分析',description:'可配置的工厂分析流程',version:'1.0.0',enabled:true,instructions:'查询各产品订单金额，生成柱状图，指出数据口径和异常。不要执行业务写操作。',inputs:{},steps:[]},true);
}
function skillModal(skill,isNew=false){
  modal(isNew?'接入新技能':'配置技能 · '+skill.name,`<p class="note">编辑技能 JSON。参数引用格式：<code>$input.quantity</code>，前序步骤结果：<code>$steps.order.id</code>。仅支持已注册业务操作，不执行任意脚本。</p><textarea id="skill-json" class="code code-editor" style="min-height:400px">${h(JSON.stringify(skill,null,2))}</textarea><div class="actions mt"><button id="save-skill" class="primary">校验并保存</button><button id="export-skill">导出配置</button></div><div id="skill-error" class="mt"></div>`);
  $('#save-skill').onclick=async()=>{try{const body=JSON.parse($('#skill-json').value);if(!isNew&&body.id!==skill.id)throw new Error('编辑已有技能时不能修改ID；请通过接入技能创建新ID');await api('/skills/'+encodeURIComponent(body.id),{method:'PUT',body:JSON.stringify(body)});$('#modal').close();toast('技能已保存，立即生效');skillsPage();}catch(error){$('#skill-error').innerHTML=errorBox(error);}};
  $('#export-skill').onclick=()=>download(new Blob([$('#skill-json').value],{type:'application/json'}),skill.id+'.json');
}

$('#shutdown-top').onclick=$('#shutdown').onclick=()=>{
  modal('关闭整个 Demo',`<p class="note">将停止网页服务、Agent 后端和 ERP/MES 后端。业务数据、对话和报表会保留，下次启动可继续使用。</p><button id="confirm-shutdown" class="danger mt">关闭整个 Demo</button><div id="shutdown-error" class="mt"></div>`);
  $('#confirm-shutdown').onclick=async()=>{try{await post('/shutdown',{});$('#modal').close();document.body.insertAdjacentHTML('beforeend','<div class="stop-screen"><div class="spark">✓</div><h1>Demo 已关闭</h1><p>所有数据已保存在本机。双击 start.cmd 可以再次启动。</p></div>');}catch(error){$('#shutdown-error').innerHTML=errorBox(error);}};
};
async function boot(){try{state.bootstrap=await api('/bootstrap');$('#connection').textContent=state.bootstrap.erp_status==='ok'?'系统在线':'业务服务离线';$('#today').textContent=new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long',timeZone:'Asia/Shanghai'});if(!state.bootstrap.key_configured)toast('未配置DeepSeek密钥，AI聊天暂不可用');await navigate(location.hash.slice(1)||'overview');}catch(error){$('#page').innerHTML=errorBox(error);$('#connection').textContent='连接失败';}}
boot();
