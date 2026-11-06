'use strict';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const h = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (v, digits=0) => Number(v || 0).toLocaleString('zh-CN', {maximumFractionDigits:digits});
const titles = {overview:'经营总览',agent:'智能助手',business:'生产与经营',reports:'报表工作室',skills:'技能与流程',admin:'账号与权限'};
const state = {page:'overview',bootstrap:null,session:null,busy:false,polling:false,run:null,report:null,charts:[]};
const statusNames = {confirmed:'待排产',in_production:'生产中',partial_shipped:'部分发货',shipped:'已发货',planned:'待开工',running:'生产中',completed:'已完工',available:'可用',maintenance:'维护中',ordered:'待收货',received:'已入库'};
const columnNames = {id:'编号',name:'名称',customer:'客户',customer_id:'客户编号',product:'产品',product_id:'产品编号',quantity:'数量',unit_price:'单价 / 元',due_date:'交货日期',status:'状态',shipped:'已发货 / m',created_at:'创建时间',machine:'设备',machine_id:'设备编号',order_id:'销售单号',work_order_id:'工单号',good_qty:'合格 / m',bad_qty:'不合格 / m',unit:'单位',stock:'库存',safety_stock:'安全库存',unit_cost:'成本单价',supplier_id:'供应商',material_id:'原料编号',spec:'规格',price:'售价 / 元',workshop:'车间',defect:'缺陷',item_type:'类型',item_id:'物料编号',reason:'原因',reference_id:'关联单号',operation:'操作',request_id:'请求标识',payload:'参数',result:'执行结果',shortage:'缺口',contact:'联系人'};
const chartTypes = {table:'明细表',pivot:'透视表',bar:'柱状图',line:'折线图',area:'面积图',pie:'饼图',scatter:'散点图',heatmap:'热力图'};

async function api(path, options={}) {
  const generation=state.authGeneration;
  const response = await fetch('/api'+path, {...options,headers:{'Content-Type':'application/json','X-Demo-Token':state.bootstrap?.token || '', 'X-Demo-User':state.bootstrap?.user.id || '', 'X-Demo-Access':state.bootstrap?.access_tag || '',...options.headers}});
  if(generation!==state.authGeneration)throw new Error('账号会话已切换');
  let data; try { data = await response.json(); } catch { throw new Error('服务响应异常，请确认Demo仍在运行'); }
  if(response.status===401 && path!='/auth/login'){showLogin();throw new Error('请重新登录');}
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
  if(path==='/bootstrap' && state.bootstrap)state.bootstrap=data;
  if(path==='/auth/session' && state.bootstrap)state.bootstrap.token=data.token;
  return data;
}
const post = (path, body) => api(path,{method:'POST',body:JSON.stringify(body)});
function toast(text) { const node=$('#toast'); node.textContent=text;node.style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.style.display='none',4000); }
function errorBox(error) { return `<div class="error">${h(error.message || error)}</div>`; }
function heading(eyebrow,title,subtitle,actions='') { return `<div class="page-heading"><div><div class="eyebrow">${h(eyebrow)}</div><h1>${h(title)}</h1><p class="subtitle">${h(subtitle)}</p></div><div class="actions">${actions}</div></div>`; }
const chartObservers=new Map(),pendingReports=new Map();
const chatReportObserver=window.IntersectionObserver?new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){const paint=pendingReports.get(entry.target);pendingReports.delete(entry.target);chatReportObserver.unobserve(entry.target);if(entry.target.isConnected)paint?.();}},{rootMargin:'300px'}):null;
function clearPendingReports(container){for(const node of pendingReports.keys())if(!container||container.contains(node)){chatReportObserver?.unobserve(node);pendingReports.delete(node);}}

function disposeChart(instance) { chartObservers.get(instance)?.disconnect();chartObservers.delete(instance);if(!instance.isDisposed())instance.dispose(); }
function disposeCharts() { clearPendingReports();state.charts.forEach(disposeChart);state.charts=[]; }
function disposeChartsWithin(container) { if(container)clearPendingReports(container);state.charts=state.charts.filter(c=>{if(c.isDisposed() || container?.contains(c.getDom())){disposeChart(c);return false;}return true;}); }
function chart(node,option) { if(!node) return; const previous=echarts.getInstanceByDom(node);if(previous)disposeChart(previous);state.charts=state.charts.filter(c=>!c.isDisposed());const instance=echarts.init(node);instance.setOption(option);state.charts.push(instance);if(window.ResizeObserver){const observer=new ResizeObserver(()=>{if(node.isConnected&&!instance.isDisposed())instance.resize();});observer.observe(node);chartObservers.set(instance,observer);}return instance; }
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
  if(!state.bootstrap)return;
  if(!titles[page] || (page==='admin'&&!isAdmin())) page='overview';
  state.page=page;location.hash=page;disposeCharts();
  $$('nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===page));$('#page-title').textContent=titles[page];
  $('#page').innerHTML='<div class="loading">正在加载…</div>';
  try { await ({overview:overview,agent:agentPage,business:businessPage,reports:reportsPage,skills:skillsPage,admin:adminPage})[page](); }
  catch(error) { if(state.page===page) $('#page').innerHTML=errorBox(error)+ '<button id="retry" class="mt">重新加载</button>'; if($('#retry'))$('#retry').onclick=()=>navigate(page); }
}
$$('nav button').forEach(b=>b.onclick=()=>navigate(b.dataset.page));
$('.brand').onclick=e=>{e.preventDefault();navigate('overview');};

async function overview() {
  const data=await api('/dashboard');if(state.page!=='overview')return;
  $('#page').innerHTML=heading('MY WORKSPACE',state.bootstrap.user.role_name+'工作台','围绕你的工作职责，查看业务进展与待办。',`<button id="refresh">↻ 刷新数据</button><button class="primary" data-prompt="请根据当前可用数据检查业务异常，并生成一张分析图表。">✳ 智能分析</button>`)+
    `<div class="kpi-grid">${data.cards.map(c=>`<div class="kpi"><div class="kpi-label">${h(c.label)}</div><div class="kpi-value">${number(c.value,2)}<small>${h(c.unit)}</small></div><div class="kpi-foot">当前负责范围</div></div>`).join('')}</div><div class="dashboard-grid">${data.sections.map(section=>`<section class="card"><div class="card-head"><h2>${h(entities[section.table])}</h2><small>最近业务记录</small></div>${table(section.data.rows)}</section>`).join('')}</div>`;
  $('#refresh').onclick=()=>navigate('overview');bindAgentButtons();
}

const entities={orders:'销售订单',work_orders:'生产工单',materials:'原料库存',products:'成品库存',purchases:'采购管理',production_reports:'报工质检',machines:'设备',shipments:'发货',stock_movements:'库存流水',bom:'物料清单',customers:'客户',suppliers:'供应商',audit:'操作审计'};
let entity='orders';
async function businessPage() {
  if(state.page!=='business')return;
  const visibleEntities=Object.fromEntries(Object.entries(entities).filter(([t])=>canTable(t)));
  if(!visibleEntities[entity])entity=Object.keys(visibleEntities)[0];
  $('#page').innerHTML=heading('ERP + MES','生产与经营','从接单到交付，所有业务记录在同一套系统中。',`<button id="business-refresh">↻ 刷新</button>${Object.keys(state.bootstrap.commands).length?'<button class="primary" id="new-command">＋ 办理业务</button>':''}`)+`<div class="tabs">${Object.entries(visibleEntities).map(([k,v])=>`<button data-entity="${k}" class="${entity===k?'selected':''}">${v}</button>`).join('')}</div><section class="card"><div class="table-toolbar"><h2>${entities[entity]}</h2><input id="data-search" aria-label="搜索当前表格" placeholder="搜索当前表格…"></div><div id="entity-data" class="loading">读取数据…</div></section><p class="note mt">数量按物料单位记录；销售、生产和发货数量均为米。业务操作自动记录审计日志。</p>`;
  $$('[data-entity]').forEach(b=>b.onclick=()=>{entity=b.dataset.entity;businessPage();});if($('#new-command'))$('#new-command').onclick=()=>businessModal();$('#business-refresh').onclick=businessPage;
  const current=entity;
  const result=await post('/query',{sql:`SELECT * FROM ${entity} ORDER BY ${state.bootstrap.user.policy.tables[entity][0]} DESC LIMIT 500`});
  if(state.page!=='business'||entity!==current)return;
  $('#entity-data').className='';$('#entity-data').innerHTML=table(result.rows);
  $('#data-search').oninput=e=>{$('#entity-data').innerHTML=table(result.rows.filter(r=>JSON.stringify(r).toLowerCase().includes(e.target.value.toLowerCase())));};
}

async function businessModal() {
  modal('办理业务',`<div class="field"><label>业务操作</label><select id="command-kind">${Object.entries(state.bootstrap.commands).map(([k,v])=>`<option value="${k}">${h(v.description.split('，')[0])}</option>`).join('')}</select></div><form id="business-form" class="mt"><div id="command-fields" class="form-grid"></div><div class="actions mt"><button type="submit" class="primary">提交业务</button></div><div id="command-result" class="mt"></div></form>`);
  const lookups={};
  await Promise.all(['customers','products','materials','machines','orders','work_orders','purchases'].filter(canTable).map(async name=>{lookups[name]=(await post('/query',{sql:`SELECT * FROM ${name} ORDER BY id DESC LIMIT 500`})).rows;}));
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
  if(state.session&&!sessions.some(s=>s.id===state.session)){state.session=null;sessionStorage.removeItem(sessionKey());}
  disposeChartsWithin($('#page'));
  $('#page').innerHTML=heading('AI WORKSPACE','把业务交给一句话。','查询、分析、执行业务。每一步都有真实数据与执行记录。',`<span class="tag">${h(state.bootstrap.model)}</span>`)+`<div class="chat-layout"><aside class="card chat-history"><button id="new-chat">＋ 新建对话</button><div class="session-list">${sessions.map(s=>`<button class="session-item ${state.session===s.id?'active':''}" data-session="${h(s.id)}">${h(s.title)}<small style="display:block">${h(s.created_at.slice(5,16).replace('T',' '))}</small></button>`).join('') || '<p class="note mt">对话会自动保存在本机</p>'}</div></aside><section class="card chat-main"><div id="chat-messages" class="chat-messages"></div><form class="chat-composer" id="chat-form"><textarea id="chat-input" aria-label="发送给智能助手的消息" placeholder="例如：查询待交付订单，分析缺料并画一张柱状图…" required></textarea><div class="composer-foot"><span id="chat-status">${state.busy?'正在处理，请稍候…':'Enter 发送 · Shift + Enter 换行'}</span><button class="primary" id="chat-send" ${state.busy?'disabled':''}>发送 ↗</button></div></form></section><aside class="card trace-panel"><div class="trace-title">执行记录 <span class="badge-count">TOOLS</span></div><div id="trace-list" class="trace-list"><p class="note">模型每次查询、业务操作和报表生成都会记录在这里。</p></div></aside></div>`;
  $('#new-chat').onclick=()=>{if(state.busy)return toast('当前任务完成后可新建对话');state.session=null;sessionStorage.removeItem(sessionKey());state.run=null;agentPage();};
  $$('[data-session]').forEach(b=>b.onclick=()=>{if(state.busy)return toast('当前任务完成后可切换对话');state.session=b.dataset.session;sessionStorage.setItem(sessionKey(),state.session);state.run=null;agentPage();});
  $('#chat-form').onsubmit=sendChat;
  $('#chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!state.busy)$('#chat-form').requestSubmit();}};
  await loadChat();
  if(state.pendingPrompt){$('#chat-input').value=state.pendingPrompt;state.pendingPrompt=null;$('#chat-input').focus();}
}
function messageHtml(role,text){return `<div class="message ${h(role)}"><div class="message-label">${role==='user'?'○ 你':'✳ 织序助手'}</div><div class="message-content ${role==='assistant'?'markdown-body':''}">${role==='assistant'?DemoUI.markdown(text):h(text)}</div></div>`;}
function drawReport(container,report) {
  disposeChartsWithin(container);container.innerHTML='';
  try {
    const view=DemoUI.reportView(report);
    if(view.kind==='empty'){container.innerHTML='<div class="empty">没有可绘制的数据</div>';return;}
    if(view.kind==='table'){container.innerHTML=table(view.rows,view.columns,false);return;}
    const node=document.createElement('div');node.className='chart chart-tall';node.setAttribute('role','img');node.setAttribute('aria-label',`${report.title} · ${chartTypes[report.chart_type]}`);container.appendChild(node);chart(node,view.option);
  } catch(error){container.innerHTML=errorBox(error);}
}
function appendChatReport(report) {
  const parent=$('#chat-messages');if(!parent || $$('[data-report-card]',parent).some(c=>c.dataset.reportCard===report.id))return;
  const card=document.createElement('section');card.className='chat-report';card.dataset.reportCard=report.id;
  card.innerHTML=`<div class="chat-report-heading"><div><span class="eyebrow">数据报表</span><h3>${h(report.title)}</h3></div><label class="report-view-label">展示<select class="report-view" aria-label="${h(report.title)}展示类型">${DemoUI.viewTypes(report).map(t=>`<option value="${h(t)}" ${t===report.chart_type?'selected':''}>${h(chartTypes[t])}</option>`).join('')}</select></label></div>${report.description?`<p class="note">${h(report.description)}</p>`:''}<div class="chat-report-view"></div><div class="chat-report-footer"><span>${h(report.data.source || 'ERP/MES')} · ${report.data.rows.length} 行${report.data.truncated?'（已截断）':''}</span><div class="actions"><a href="/api/reports/${encodeURIComponent(report.id)}/csv">导出 CSV</a><button class="open-report">打开报表 ↗</button></div></div>`;
  parent.appendChild(card);
  let nav=$('#chat-artifacts');
  if(!nav){nav=document.createElement('div');nav.id='chat-artifacts';nav.className='chat-artifact-nav';nav.setAttribute('aria-label','对话报表快捷入口');parent.before(nav);const label=document.createElement('span');label.textContent='本对话报表';nav.appendChild(label);}
  const jump=document.createElement('button');jump.textContent=report.title;jump.title=report.title;jump.onclick=()=>card.scrollIntoView({block:'center',behavior:'smooth'});nav.appendChild(jump);
  const paint=()=>{pendingReports.delete(card);chatReportObserver?.unobserve(card);drawReport($('.chat-report-view',card),DemoUI.withAxes(report,$('.report-view',card).value));};
  $('.report-view',card).onchange=paint;$('.open-report',card).onclick=()=>{state.report=report.id;navigate('reports');};if(chatReportObserver){$('.chat-report-view',card).innerHTML='<div class="loading">图表将在进入视野时绘制…</div>';pendingReports.set(card,paint);chatReportObserver.observe(card);}else paint();
}
async function loadChat(){
  if(state.page!=='agent')return;
  if(!state.session){$('#chat-messages').innerHTML=`<div class="chat-welcome"><span class="spark">✳</span><h2>今天，想从哪里开始？</h2><p class="subtitle">${Object.keys(state.bootstrap.commands).length?'我可以帮你分析业务，也可以办理岗位内的业务。':'我可以帮你查询业务数据、分析趋势并生成图表。'}</p><div class="suggestions">${suggestions().map(prompt=>`<button data-prompt="${h(prompt)}">${h(prompt)} ↗</button>`).join('')}</div></div>`;$$('#chat-messages [data-prompt]').forEach(b=>b.onclick=()=>{$('#chat-input').value=b.dataset.prompt;$('#chat-input').focus();});return;}
  const sessionId=state.session,session=await api('/sessions/'+sessionId);if(state.page!=='agent'||state.session!==sessionId)return;
  renderHistory(session.messages,session.has_more,session.before_id,sessionId);
  const last=session.runs.at(-1);if(last){state.run=last.id;const run=await loadRunEvents(last.id,sessionId);if(state.page!=='agent'||state.session!==sessionId)return;if(last.status==='running'&&!state.polling){state.busy=true;pollRun(last.id);}else if(last.status==='interrupted'){$('#trace-list').innerHTML+=errorBox('上次执行因服务重启中断，请核对业务记录后继续。');}}
  if(last&&last.status!=='running')$('#chat-status').textContent=last.status==='completed'?'任务已完成 · 可从上方报表入口查看图表':'任务未完成 · 请查看执行记录';
  $('#chat-messages').scrollTop=$('#chat-messages').scrollHeight;
}
function renderHistory(messages,hasMore,beforeId,sessionId){
  disposeChartsWithin($('#chat-messages'));$('#chat-artifacts')?.remove();$('#chat-messages').innerHTML='';
  if(hasMore){
    const button=document.createElement('button');button.textContent='加载更早的消息';button.id='older-messages';$('#chat-messages').appendChild(button);
    button.onclick=async()=>{button.disabled=true;try{const previous=await api('/sessions/'+sessionId+'?before='+beforeId);if(state.page!=='agent'||state.session!==sessionId)return;
      const height=$('#chat-messages').scrollHeight;renderHistory([...previous.messages,...messages],previous.has_more,previous.before_id,sessionId);$('#chat-messages').scrollTop=$('#chat-messages').scrollHeight-height;
    }catch(error){toast(error.message);button.disabled=false;}};
  }
  for(const entry of DemoUI.chatEntries(messages)){
    if(entry.kind==='report')appendChatReport(entry.report);
    else $('#chat-messages').insertAdjacentHTML('beforeend',messageHtml(entry.role,entry.text));
  }
}
async function loadRunEvents(id,sessionId){
  let after=0,run;$('#trace-list').innerHTML='';
  do{run=await api('/runs/'+id+'?after='+after);if(state.page!=='agent'||state.session!==sessionId)return run;
    for(const event of run.events){after=event.id;renderEvent(event);}
  }while(run.has_more);
  state.eventCursor={id,after};return run;
}
async function sendChat(e){
  e.preventDefault();if(state.busy)return;const text=$('#chat-input').value.trim();if(!text)return;
  state.busy=true;$('#chat-send').disabled=true;$('#chat-input').value='';$('#chat-status').textContent='正在提交任务…';
  try{const result=await post('/chat',{message:text,session_id:state.session});state.session=result.session_id;sessionStorage.setItem(sessionKey(),state.session);state.run=result.run_id;await agentPage();if(!state.polling)pollRun(result.run_id);}
  catch(error){state.busy=false;toast(error.message);if($('#chat-send'))$('#chat-send').disabled=false;if($('#chat-input'))$('#chat-input').value=text;}
}
function renderEvent(e){
  if(e.kind==='tool_result'&&e.payload.ok&&e.payload.name==='create_report')appendChatReport(e.payload.result);
  const parent=$('#trace-list');if(!parent||parent.querySelector(`[data-event="${e.id}"]`))return;
  const p=e.payload;
  if(e.kind==='tool_start')parent.insertAdjacentHTML('beforeend',`<details class="trace-event" data-event="${e.id}"><summary>↗ ${h(p.name)}</summary><pre></pre></details>`);
  if(e.kind==='tool_result'){
    parent.insertAdjacentHTML('beforeend',`<details class="trace-event ${p.ok?'':'fail'}" data-event="${e.id}"><summary>${p.ok?'✓':'!'} ${h(p.name)} ${p.ok?'完成':'未成功'}</summary><pre></pre></details>`);
    if(p.ok&&p.name==='create_report') {const b=document.createElement('button');b.className='artifact-link';b.textContent='◷ '+p.result.title;b.onclick=()=>{state.report=p.result.id;navigate('reports');};parent.appendChild(b);}
  }
  if(e.kind==='status') {parent.insertAdjacentHTML('beforeend',`<div class="trace-status" data-event="${e.id}">${h(p.message)}</div>`);if($('#chat-status'))$('#chat-status').textContent=p.message;}
  if(e.kind==='error')parent.insertAdjacentHTML('beforeend',`<div class="error" data-event="${e.id}">${h(p.message)}</div>`);
  const details=parent.querySelector(`details[data-event="${e.id}"]`);if(details)details.ontoggle=()=>{if(details.open&&!details.dataset.loaded){$('pre',details).textContent=JSON.stringify(e.kind==='tool_start'?p.arguments:p.result||p.error,null,2);details.dataset.loaded='1';}};
  parent.scrollTop=parent.scrollHeight;
}
async function pollRun(id){
  if(state.polling)return;state.polling=true;let after=state.eventCursor?.id===id?state.eventCursor.after:0;const generation=state.authGeneration;
  try{while(generation===state.authGeneration){const run=await api('/runs/'+id+'?after='+after);for(const e of run.events){after=e.id;if(state.page==='agent'&&state.run===id)renderEvent(e);}
    if(run.has_more)continue;
    if(run.status!=='running'){state.busy=false;if(state.page==='agent'){await loadChat();if($('#chat-send'))$('#chat-send').disabled=false;if($('#chat-status'))$('#chat-status').textContent=`${run.status==='completed'?'已完成':'未完成'} · 模型调用 ${run.usage.model_calls||0} 次 · ${number((run.usage.prompt_tokens||0)+(run.usage.completion_tokens||0))} tokens`;}else toast(run.status==='completed'?'助手任务已完成':'助手任务未完成，请查看执行记录');break;}
    await new Promise(resolve=>setTimeout(resolve,1200));
  }}catch(error){if(generation===state.authGeneration){state.busy=false;toast('连接中断：'+error.message);if($('#chat-send'))$('#chat-send').disabled=false;}}finally{if(generation===state.authGeneration)state.polling=false;}
}

let reportDraft={title:'产品订单金额',chart_type:'bar',sql:'SELECT p.name AS 产品, ROUND(SUM(o.quantity*o.unit_price),2) AS 订单金额 FROM orders o JOIN products p ON p.id=o.product_id GROUP BY p.id,p.name ORDER BY 订单金额 DESC',rows:[],x:'',y:[],group:'',description:''};
let reportColumns=[],reportGridPage=0;
async function reportsPage(){
  const reports=await api('/reports');if(state.page!=='reports')return;
  if(!state.report&&!reportDraft.rows.length&&reports.length)state.report=reports[0].id;
  if(state.report){const saved=await api('/reports/'+state.report);reportDraft={...saved,rows:saved.data.rows.map(r=>({...r}))};reportColumns=[...saved.data.columns];}
  if(state.page!=='reports')return;disposeChartsWithin($('#page'));
  $('#page').innerHTML=heading('REPORT STUDIO','让数据，呈现更多可能。','AI生成报表，也可以在线编辑数据、切换图形，保存与导出。',`<button class="primary" id="new-report">＋ 新建报表</button>`)+`<div class="report-layout"><aside class="card report-list"><h2>已保存的报表 <span class="badge-count">${reports.length}</span></h2>${reports.map(r=>`<button class="report-item ${r.id===state.report?'active':''}" data-report="${r.id}">${h(r.title)}<small>${h(chartTypes[r.chart_type])} · ${h(r.created_at.slice(5,16).replace('T',' '))}</small></button>`).join('') || '<p class="note mt">向助手提出报表需求，或在右侧绘制第一张报表。</p>'}</aside><section class="card"><div class="card-body"><div class="form-grid"><div class="field"><label>报表名称</label><input id="report-title" value="${h(reportDraft.title)}"></div><div class="field"><label>展示类型</label><select id="report-type">${Object.entries(chartTypes).map(([k,v])=>`<option value="${k}" ${k===reportDraft.chart_type?'selected':''}>${v}</option>`).join('')}</select></div></div><div class="field mt"><label>数据说明 / 分析口径</label><input id="report-description" value="${h(reportDraft.description)}" placeholder="例如：订单金额按下单日期统计，不代表实收"></div><details class="mt" ${reportDraft.rows.length?'':'open'}><summary class="note">SQL 数据源（只读）</summary><textarea id="report-sql" class="code code-editor" aria-label="只读SQL查询">${h(reportDraft.sql)}</textarea><button id="run-query" class="mt">↻ 查询数据</button></details><div class="editor-grid mt" id="chart-fields"></div><div class="editor-table" id="editable-data"></div><div class="actions mt"><button id="add-row">＋ 行</button><button id="add-column">＋ 列</button><button id="import-json">导入 JSON</button><button id="preview-chart" class="soft">预览图表</button><button id="save-report" class="primary">保存报表</button><button id="export-csv">导出 CSV</button><button id="export-png">导出 PNG</button></div><div id="report-error" class="mt"></div><div class="report-preview"><h2 id="preview-title">${h(reportDraft.title)}</h2><div id="report-chart"></div><div id="report-table"></div><div class="report-meta"><span id="report-source">${h(reportDraft.data?.source || '查询数据后可开始绘图')}</span><span>${h(reportDraft.data?.as_of || '')}</span></div></div></div></section></div>`;
  $$('[data-report]').forEach(b=>b.onclick=()=>{state.report=b.dataset.report;reportsPage();});
  $('#new-report').onclick=()=>{state.report=null;reportDraft={title:'新建报表',chart_type:'table',rows:[{'项目':'样例 A','数值':10},{'项目':'样例 B','数值':20}],sql:'',x:'项目',y:['数值'],group:'',description:''};reportColumns=['项目','数值'];reportsPage();};
  $('#run-query').onclick=async()=>{try{const data=await post('/query',{sql:$('#report-sql').value});reportDraft.sql=$('#report-sql').value;reportDraft.rows=data.rows;reportDraft.data=data;reportColumns=data.columns;$('#report-source').textContent=data.source+(data.truncated?' · 结果已截断，请缩小查询范围':'');renderGrid();renderChartFields();previewReport();}catch(error){$('#report-error').innerHTML=errorBox(error);}};
  $('#report-type').onchange=()=>{readDraft();renderChartFields();previewReport();};
  $('#add-row').onclick=()=>{if(reportDraft.rows.length>=500)return toast('最多500行');if(!reportColumns.length)reportColumns=['项目','数值'];reportDraft.rows.push(Object.fromEntries(reportColumns.map((c,i)=>[c,i===0?'新项目':0])));manualData();renderGrid();renderChartFields();};
  $('#add-column').onclick=()=>{const name=prompt('新列名称');if(!name)return;if(reportColumns.includes(name))return toast('列名已存在');if(reportColumns.length>=50)return toast('最多50列');reportColumns.push(name);reportDraft.rows.forEach(r=>r[name]=0);manualData();renderGrid();renderChartFields();};
  $('#import-json').onclick=()=>{modal('导入表格数据',`<p class="note">输入对象数组，每行使用相同列名。例如 [{"产品":"府绸","数量":100}]</p><textarea id="json-import" class="code code-editor">${h(JSON.stringify(reportDraft.rows,null,2))}</textarea><button id="json-import-confirm" class="primary mt">导入</button><div id="json-import-error" class="mt"></div>`);$('#json-import-confirm').onclick=()=>{try{const data=JSON.parse($('#json-import').value);if(!Array.isArray(data)||!data.length||data.length>500||data.some(r=>!r||Array.isArray(r)||typeof r!=='object'))throw new Error('需要1至500行对象数组');const cols=Object.keys(data[0]);if(!cols.length||cols.length>50||data.some(r=>Object.keys(r).length!==cols.length||cols.some(c=>!(c in r))||Object.values(r).some(v=>v!==null&&typeof v==='object')))throw new Error('列名必须一致，单元格只能是数字、文本、布尔值或null');reportDraft.rows=data;reportColumns=cols;manualData();renderGrid();renderChartFields();previewReport();$('#modal').close();}catch(error){$('#json-import-error').innerHTML=errorBox(error);}};};
  $('#preview-chart').onclick=previewReport;
  $('#save-report').onclick=async()=>{const button=$('#save-report');button.disabled=true;try{readDraft();const payload={title:reportDraft.title,chart_type:reportDraft.chart_type,sql:reportDraft.sql,rows:reportDraft.sql?[]:reportDraft.rows,x:reportDraft.x,y:reportDraft.y,group:reportDraft.group,description:reportDraft.description};const result=await post('/reports',payload);state.report=result.id;toast('报表快照已保存');await reportsPage();}catch(error){$('#report-error').innerHTML=errorBox(error);}finally{if($('#save-report'))$('#save-report').disabled=false;}};
  $('#export-csv').onclick=()=>{readDraft();const safe=v=>{let s=String(v??'');if(/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};const text='\ufeff'+[reportColumns.map(safe).join(','),...reportDraft.rows.map(r=>reportColumns.map(c=>safe(r[c])).join(','))].join('\r\n');download(new Blob([text],{type:'text/csv;charset=utf-8'}),reportDraft.title+'.csv');};
  $('#export-png').onclick=()=>{const node=$('#report-chart .chart'),instance=node&&echarts.getInstanceByDom(node);if(!instance)return toast('请先预览图形；表格可导出CSV');const a=document.createElement('a');a.href=instance.getDataURL({type:'png',pixelRatio:2,backgroundColor:'#fff'});a.download=reportDraft.title+'.png';a.click();};
  renderGrid();renderChartFields();if(reportDraft.rows.length)previewReport();
}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function manualData(){reportDraft.sql='';if($('#report-sql'))$('#report-sql').value='';if($('#report-source'))$('#report-source').textContent='手工编辑数据（已断开原SQL，保存当前编辑内容）';}
function renderGrid(){
  const pages=Math.max(1,Math.ceil(reportDraft.rows.length/50));reportGridPage=Math.min(reportGridPage,pages-1);const offset=reportGridPage*50;
  $('#editable-data').innerHTML=reportColumns.length?`<table><thead><tr>${reportColumns.map(c=>`<th>${h(c)}</th>`).join('')}<th>操作</th></tr></thead><tbody>${reportDraft.rows.slice(offset,offset+50).map((row,index)=>{const i=offset+index;return `<tr>${reportColumns.map((c,j)=>`<td><input aria-label="第${i+1}行 ${h(c)}" data-row="${i}" data-col="${j}" value="${h(row[c])}"></td>`).join('')}<td><button data-remove-row="${i}">删除</button></td></tr>`;}).join('')}</tbody></table>`:'<div class="empty">执行查询，或添加列和数据行开始绘图</div>';
  if(pages>1){$('#editable-data').insertAdjacentHTML('beforeend',`<div class="actions mt"><button id="grid-prev" ${reportGridPage===0?'disabled':''}>上一页</button><span>第 ${reportGridPage+1} / ${pages} 页 · 共 ${reportDraft.rows.length} 行</span><button id="grid-next" ${reportGridPage===pages-1?'disabled':''}>下一页</button></div>`);$('#grid-prev').onclick=()=>{reportGridPage--;renderGrid();};$('#grid-next').onclick=()=>{reportGridPage++;renderGrid();};}
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
  $('#report-table').innerHTML='';
  drawReport($('#report-chart'),{...reportDraft,data:{rows:reportDraft.rows,columns:reportColumns}});
}

async function skillsPage(){
  const skills=await api('/skills');if(state.page!=='skills')return;
  $('#page').innerHTML=heading('SKILLS & WORKFLOWS','把经验，变成可复用的能力。','使用岗位知识与自动化流程，让助手协助日常工作。',`${isAdmin()?'<button id="add-skill" class="primary">＋ 接入技能</button>':''}`)+`<div class="skill-grid">${skills.map((s,i)=>`<section class="card skill-card"><div class="actions" style="justify-content:space-between"><div class="skill-icon">${['⌘','▦','☀'][i%3]}</div>${isAdmin()?`<label class="switch"><input type="checkbox" data-skill-toggle="${h(s.id)}" ${s.enabled?'checked':''}>启用</label>`:''}</div><h2>${h(s.name)}</h2><p>${h(s.description)}</p><span class="note">${s.steps.length?'事务流程 · '+s.steps.length+' 个步骤':'分析指南 · 自主组合工具'} <span style="float:right">v${h(s.version)}</span></span><div class="actions">${isAdmin()?`<button data-edit-skill="${h(s.id)}">配置技能</button>`:''}<button class="soft" data-use-skill="${h(s.id)}" ${s.enabled?'':'disabled'}>交给助手 ↗</button></div></section>`).join('')}</div><div class="inline-note">技能可包含领域指令、输入参数和业务步骤。流程中的步骤会在同一事务内提交，失败全部回滚。启用状态和配置修改立即生效，业务规则始终由系统后端校验。</div>`;
  $$('[data-skill-toggle]').forEach(input=>input.onchange=async()=>{const skill=skills.find(s=>s.id===input.dataset.skillToggle);try{await api('/skills/'+skill.id,{method:'PUT',body:JSON.stringify({...skill,enabled:input.checked})});toast(input.checked?'技能已启用':'技能已禁用');skillsPage();}catch(error){input.checked=!input.checked;toast(error.message);}});
  $$('[data-edit-skill]').forEach(b=>b.onclick=()=>skillModal(skills.find(s=>s.id===b.dataset.editSkill)));
  $$('[data-use-skill]').forEach(b=>b.onclick=()=>{const skill=skills.find(s=>s.id===b.dataset.useSkill);setAgentPrompt(`请使用“${skill.name}”技能（${skill.id}）。${skill.steps.length?'先读取技能并告诉我需要补充哪些业务参数。':'执行检查并生成相应报表。'}`);});
  if($('#add-skill'))$('#add-skill').onclick=()=>skillModal({id:'custom-review',name:'自定义经营分析',description:'可配置的工厂分析流程',version:'1.0.0',enabled:true,instructions:'查询各产品订单金额，生成柱状图，指出数据口径和异常。不要执行业务写操作。',inputs:{},steps:[]},true);
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

function isAdmin(){return state.bootstrap?.user.role_id==='admin';}
function canTable(name){return Boolean(state.bootstrap?.user.policy.tables[name]);}
function sessionKey(){return 'demo-session-'+state.bootstrap?.user.id;}
function suggestions(){
  const prompts=['检查当前业务数据并生成一张分析柱状图。'];
  if(canTable('orders'))prompts.push('查询待交付订单，按产品数量绘制饼图。');
  if(canTable('materials'))prompts.push('检查原料安全库存缺口，生成补料建议表。');
  if(canTable('production_reports'))prompts.push('分析生产良品率，生成质量趋势图。');
  return prompts;
}
function showLogin(){
  state.authGeneration=(state.authGeneration||0)+1;
  disposeCharts();state.bootstrap=null;state.page='login';state.session=null;state.report=null;state.run=null;state.pendingPrompt=null;state.eventCursor=null;state.busy=false;state.polling=false;
  reportDraft={title:'新建报表',chart_type:'table',sql:'',rows:[],x:'',y:[],group:'',description:''};reportColumns=[];reportGridPage=0;
  $('#modal').close();$('#modal-body').innerHTML='';$('#page').innerHTML='';$('#identity').textContent='';
  $$('[data-shell]').forEach(n=>n.hidden=true);$('#login-screen').hidden=false;$('#login-password').value='';
}
async function boot(){
  try{
    state.bootstrap=await api('/bootstrap');const user=state.bootstrap.user;
    state.session=sessionStorage.getItem(sessionKey());
    $('#identity').innerHTML=h(user.name)+'<small>'+h(user.role_name)+'</small>';
    $('[data-page="admin"]').hidden=!isAdmin();$('#shutdown').hidden=$('#shutdown-top').hidden=!isAdmin();
    const skills=await api('/skills');$('[data-page="skills"]').hidden=!skills.length;
    $('#login-screen').hidden=true;$$('[data-shell]').forEach(n=>n.hidden=false);
    $('#connection').textContent=state.bootstrap.erp_status==='ok'?'系统在线':'业务服务离线';
    $('#today').textContent=new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long',timeZone:'Asia/Shanghai'});
    const first=Object.keys(user.policy.tables)[0];
    reportDraft={title:'业务分析',chart_type:'table',sql:`SELECT * FROM ${first} LIMIT 100`,rows:[],x:'',y:[],group:'',description:''};
    await navigate(location.hash.slice(1)||'overview');
  }catch(error){showLogin();if(error.message!=='请重新登录')$('#login-error').innerHTML=errorBox(error);}
}
$('#login-form').onsubmit=async e=>{
  e.preventDefault();const button=$('button',e.target);button.disabled=true;$('#login-error').innerHTML='';
  try{await api('/auth/login',{method:'POST',headers:{'X-Demo-Login':'1'},body:JSON.stringify({username:$('#login-username').value,password:$('#login-password').value})});$('#login-password').value='';await boot();}
  catch(error){$('#login-error').innerHTML=errorBox(error);}finally{button.disabled=false;}
};
$('#logout').onclick=async()=>{try{await post('/auth/logout',{});showLogin();location.hash='';}catch(error){toast(error.message);}};
// Revalidate after switching tabs so revoked accounts do not retain a visible workspace.
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.bootstrap)api('/auth/session').catch(()=>{});});
setInterval(()=>{if(!document.hidden&&state.bootstrap)api('/auth/session').catch(()=>{});},30000);
async function adminPage(){
  const data=await api('/admin');if(state.page!=='admin')return;
  $('#page').innerHTML=heading('ACCESS MANAGEMENT','账号与岗位','维护岗位职责与数据范围。授权修改后，受影响账号需要重新登录。','<button class="primary" id="add-user">＋ 新建账号</button>')+
    `<section class="card"><div class="card-head"><h2>工作账号</h2></div><div class="table-wrap"><table><thead><tr><th>账号</th><th>姓名</th><th>岗位</th><th>负责客户</th><th>状态</th><th>操作</th></tr></thead><tbody>${data.users.map(u=>`<tr><td>${h(u.username)}</td><td>${h(u.name)}</td><td>${h(data.roles.find(r=>r.id===u.role_id)?.name)}</td><td>${h(u.customer_ids.join('、')||'按岗位范围')}</td><td>${u.active?'启用':'停用'}</td><td><button data-user="${h(u.id)}">编辑</button></td></tr>`).join('')}</tbody></table></div></section><h2 class="mt">岗位授权</h2><div class="skill-grid">${data.roles.map(r=>`<section class="card skill-card"><h2>${h(r.name)}</h2><p>${Object.keys(r.policy.tables).length} 类数据 · ${r.policy.commands.length} 项业务操作</p><p class="note">${r.policy.scope==='customers'?'仅分配客户及关联订单':'岗位授权数据全范围'}</p>${r.id==='admin'?'<span class="tag">系统管理岗位</span>':`<button data-role="${h(r.id)}">配置读写权限</button>`}</section>`).join('')}</div>`;
  $('#add-user').onclick=()=>userEditor({id:crypto.randomUUID(),username:'',name:'',role_id:'sales',customer_ids:[],active:true},data,true);
  $$('[data-user]').forEach(b=>b.onclick=()=>userEditor(data.users.find(u=>u.id===b.dataset.user),data,false));
  $$('[data-role]').forEach(b=>b.onclick=()=>roleEditor(data.roles.find(r=>r.id===b.dataset.role),data));
}
function userEditor(user,data,isNew){
  modal(isNew?'新建工作账号':'编辑工作账号',`<form id="user-form"><div class="form-grid"><div class="field"><label>账号</label><input name="username" value="${h(user.username)}" pattern="[a-z][a-z0-9_-]{2,39}" required></div><div class="field"><label>姓名</label><input name="name" value="${h(user.name)}" required maxlength="80"></div><div class="field"><label>岗位</label><select name="role_id">${data.roles.map(r=>`<option value="${h(r.id)}" ${r.id===user.role_id?'selected':''}>${h(r.name)}</option>`).join('')}</select></div><div class="field"><label>${isNew?'初始密码':'重置密码（留空保持）'}</label><input name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" ${isNew?'required':''}></div></div><div class="field mt"><label>负责客户编号（客户范围岗位，逗号分隔）</label><input name="customer_ids" value="${h(user.customer_ids.join(','))}" placeholder="C001,C002"></div><label class="mt"><input name="active" type="checkbox" ${user.active?'checked':''}> 启用账号</label><p class="note mt">保存会注销该账号的现有登录。数据权限变化后，旧范围的聊天和报表不再展示。</p><button class="primary mt">保存账号</button><div id="user-error" class="mt"></div></form>`);
  $('#user-form').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);const body=Object.fromEntries(f);body.active=f.has('active');body.customer_ids=body.customer_ids.split(/[,，]/).map(v=>v.trim()).filter(Boolean);
    try{await api('/admin/users/'+encodeURIComponent(user.id),{method:'PUT',body:JSON.stringify(body)});$('#modal').close();if(user.id===state.bootstrap?.user.id){showLogin();return;}await adminPage();toast('账号已保存');}catch(error){if($('#user-error'))$('#user-error').innerHTML=errorBox(error);}};
}
function roleEditor(role,data){
  modal('岗位授权 · '+role.name,`<form id="role-form"><div class="field"><label>岗位名称</label><input name="name" value="${h(role.name)}" required maxlength="80"></div><div class="field mt"><label>数据范围</label><select name="scope"><option value="all" ${role.policy.scope==='all'?'selected':''}>授权表的全部数据</option><option value="customers" ${role.policy.scope==='customers'?'selected':''}>账号负责客户及关联数据</option></select></div><h3 class="mt">可读取的数据与字段</h3><div class="permission-matrix">${Object.entries(data.tables).filter(([t])=>t!=='audit').map(([t,cols])=>`<details ${role.policy.tables[t]?'open':''}><summary>${h(entities[t])}</summary><div class="permission-fields">${cols.map(c=>`<label><input type="checkbox" data-table="${t}" data-column="${c}" ${role.policy.tables[t]?.includes(c)?'checked':''}>${h(columnNames[c]||c)}</label>`).join('')}</div></details>`).join('')}</div><h3 class="mt">可执行的业务</h3><div class="permission-fields">${data.commands.map(c=>`<label><input type="checkbox" data-operation="${c}" ${role.policy.commands.includes(c)?'checked':''}>${h(state.bootstrap.commands[c]?.description.split('，')[0]||c)}</label>`).join('')}</div><p class="note mt">未勾选的数据、字段和业务将不可见。客户范围只支持客户、产品、BOM、订单及相关生产发货数据。</p><button class="primary mt">保存授权</button><div id="role-error" class="mt"></div></form>`);
  $('#role-form').onsubmit=async e=>{e.preventDefault();const form=new FormData(e.target);const policy={tables:{},commands:$$('[data-operation]:checked').map(n=>n.dataset.operation),scope:form.get('scope')};$$('[data-column]:checked').forEach(n=>(policy.tables[n.dataset.table]??=[]).push(n.dataset.column));
    try{await api('/admin/roles/'+role.id,{method:'PUT',body:JSON.stringify({name:form.get('name'),policy})});$('#modal').close();await adminPage();toast('岗位授权已更新');}catch(error){$('#role-error').innerHTML=errorBox(error);}};
}
boot();
