const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const echarts=require('../frontend/vendor/echarts.min.js');
const root=path.resolve(__dirname,'..');
const source=name=>fs.readFileSync(path.join(root,'frontend',name),'utf8');

function environment(html='<!doctype html><body></body>'){
  const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://localhost:8765/'});
  for(const file of ['vendor/marked.umd.js','vendor/purify.min.js','renderers.js'])dom.window.eval(source(file));
  return dom;
}
const report=(type='bar',id='RPT-test')=>({id,title:'产品订单金额',chart_type:type,x:'产品',y:['金额'],group:'月份',description:'按订单统计',data:{columns:['产品','金额','月份'],rows:[{'产品':'府绸','金额':120,'月份':'11月'},{'产品':'牛仔','金额':80,'月份':'11月'}],source:'ERP/MES'}});
const toolMessages=r=>[
  {body:{role:'assistant',content:null,tool_calls:[{id:'call-'+r.id,function:{name:'create_report'}}]}},
  {body:{role:'tool',tool_call_id:'call-'+r.id,content:JSON.stringify({ok:true,result:r})}}
];

test('Markdown renders headings, emphasis, lists, tables, blockquotes and fenced code',()=>{
  const dom=environment(),d=dom.window.document;
  d.body.innerHTML=dom.window.DemoUI.markdown('# 经营分析\n\n**重点**和*说明*\n\n- 检查库存\n- 排产\n\n| 产品 | 金额 |\n| --- | ---: |\n| 府绸 | 120 |\n\n> 仅为订单金额\n\n```sql\nSELECT * FROM orders;\n```');
  assert.equal(d.querySelector('h1').textContent,'经营分析');
  assert.equal(d.querySelector('strong').textContent,'重点');
  assert.equal(d.querySelectorAll('li').length,2);
  assert.equal(d.querySelector('.table-wrap table tbody td').textContent,'府绸');
  assert.equal(d.querySelector('blockquote p').textContent.trim(),'仅为订单金额');
  assert.match(d.querySelector('pre code').textContent,/SELECT/);dom.window.close();
});

test('Markdown strips scripts, event handlers, dangerous links and spoofed UI attributes',()=>{
  const dom=environment(),d=dom.window.document;
  d.body.innerHTML=dom.window.DemoUI.markdown('<script>alert(1)</script>\n<img src=x onerror="alert(2)">\n\n[bad](javascript:alert(3))\n\n<a href="data:text/html,evil" onclick="alert(4)" data-report-card="evil">bad</a>\n\n<svg onload="alert(5)"></svg>\n\n[doc](https://example.com)\n\n- [x] 完成');
  assert.equal(d.querySelector('script,img,svg,[onclick],[onerror],[data-report-card]'),null);
  for(const a of d.querySelectorAll('a'))assert.doesNotMatch(a.getAttribute('href') || '',/^(javascript|data):/);
  const link=d.querySelector('a[href="https://example.com"]');assert.equal(link.rel,'noopener noreferrer');
  assert.equal(d.querySelector('input').disabled,true);dom.window.close();
});

test('Historical report cards survive subsequent text-only turns and deduplicate tool results',()=>{
  const dom=environment(),r=report(),messages=[{body:{role:'user',content:'画图'}},...toolMessages(r),{body:{role:'assistant',content:'**完成**'}},{body:{role:'user',content:'谢谢'}},{body:{role:'assistant',content:'好的'}},...toolMessages(r)];
  const entries=dom.window.DemoUI.chatEntries(messages);
  assert.equal(entries.filter(e=>e.kind==='report').length,1);
  assert.equal(entries[1].report.id,r.id);
  assert.equal(entries.at(-1).text,'好的');
  assert.equal(dom.window.DemoUI.chatEntries([{body:{role:'tool',content:JSON.stringify({ok:true,result:r})}}]).length,0);dom.window.close();
});

for(const type of ['bar','pie','line','area','scatter','heatmap','pivot','table']){
  test(`Report renderer produces ${type} using actual ECharts SVG output`,()=>{
    const dom=environment(),r=report(type);
    if(type==='scatter'){r.x='金额';r.y=['金额'];}
    const view=dom.window.DemoUI.reportView(r);
    if(['table','pivot'].includes(type)){assert.equal(view.kind,'table');assert.equal(view.rows.length,2);}
    else{
      assert.equal(view.kind,'chart');
      const instance=echarts.init(null,null,{renderer:'svg',ssr:true,width:600,height:360});
      instance.setOption({...view.option,animation:false});
      const svg=instance.renderToSVGString();
      assert.match(svg,/<svg/);assert.match(svg,/<path/);
      assert.equal(instance.getOption().series[0].type,type==='area'?'line':type);
      instance.dispose();
    }
    dom.window.close();
  });
}

test('A historical table snapshot can be switched to bar or pie without invented values',()=>{
  const dom=environment(),ui=dom.window.DemoUI,r=report('table');r.x='';r.y=[];
  assert.ok(ui.viewTypes(r).includes('bar'));assert.ok(ui.viewTypes(r).includes('pie'));
  const view=ui.reportView(ui.withAxes(r,'pie'));
  assert.deepEqual(Array.from(view.option.series[0].data,d=>d.value),[120,80]);
  const bad=report();bad.data.rows[0]['金额']='not numeric';
  assert.throws(()=>ui.reportView(bad),/数值列/);dom.window.close();
});

test('Full chat integration renders Markdown and both historical/live chart cards; studio uses same chart renderer',async()=>{
  const dom=environment(source('index.html')),w=dom.window;
  const r=report('bar','RPT-bar'),live=report('pie','RPT-pie'),instances=new Map();
  w.echarts={getInstanceByDom:n=>instances.get(n),init:n=>{
    const c={node:n,disposed:false,setOption(o){this.option=o;},getDom(){return n;},resize(){},isDisposed(){return this.disposed;},dispose(){this.disposed=true;instances.delete(n);}};instances.set(n,c);return c;
  }};
  w.ResizeObserver=class{observe(){}disconnect(){}};
  w.fetch=async url=>({ok:true,json:async()=>{
    const p=String(url).replace('/api','');
    if(p==='/skills')return [];
    if(p==='/bootstrap')return {user:{id:'admin',role_id:'admin',name:'管理员',role_name:'管理员',policy:{tables:{orders:['id']}}},token:'test',erp_status:'ok',model:'test',key_configured:true,commands:{}};
    if(p==='/sessions')return [{id:'S1',title:'图表测试',created_at:'2026-11-06T10:00:00'}];
    if(p==='/sessions/S1')return {messages:[...toolMessages(r),{body:{role:'assistant',content:'## 结果\n\n**已生成**\n\n| 产品 | 金额 |\n| --- | --- |\n| 府绸 | 120 |'},role:'assistant'}],runs:[]};
    if(p==='/reports')return [{id:r.id,title:r.title,chart_type:'bar',created_at:'2026-11-06T10:00:00'}];
    if(p==='/reports/'+r.id)return {...r,sql:'SELECT 1',created_at:'2026-11-06T10:00:00'};
    throw new Error('Unexpected request '+p);
  }});
  w.location.hash='agent';w.eval(source('app.js')+'\nwindow.testUI={renderEvent,loadChat,disposeCharts};');
  for(let i=0;i<20&&!w.document.querySelector('[data-session]');i++)await new Promise(r=>setTimeout(r,5));
  w.document.querySelector('[data-session]').click();
  for(let i=0;i<20&&!w.document.querySelector('[data-report-card]');i++)await new Promise(r=>setTimeout(r,5));
  assert.equal(w.document.querySelector('.markdown-body h2').textContent,'结果');
  assert.ok(w.document.querySelector('.markdown-body table'));
  let card=w.document.querySelector('[data-report-card="RPT-bar"]');
  assert.equal(instances.get(card.querySelector('.chart')).option.series[0].type,'bar');
  const select=card.querySelector('select');select.value='pie';select.dispatchEvent(new w.Event('change'));
  assert.equal(instances.get(card.querySelector('.chart')).option.series[0].type,'pie');
  w.liveEvent={id:99,kind:'tool_result',payload:{name:'create_report',ok:true,result:live}};
  w.testUI.renderEvent(w.liveEvent);w.testUI.renderEvent(w.liveEvent);
  assert.equal(w.document.querySelectorAll('[data-report-card="RPT-pie"]').length,1);
  assert.equal(instances.get(w.document.querySelector('[data-report-card="RPT-pie"] .chart')).option.series[0].type,'pie');
  assert.equal(w.document.querySelectorAll('#chat-artifacts button').length,2);
  assert.equal(w.sessionStorage.getItem('demo-session-admin'),'S1');
  await w.testUI.loadChat();assert.equal(instances.size,1);
  w.document.querySelector('.open-report').click();
  for(let i=0;i<20&&!w.document.querySelector('#report-chart .chart');i++)await new Promise(r=>setTimeout(r,5));
  assert.equal(instances.get(w.document.querySelector('#report-chart .chart')).option.series[0].type,'bar');
  assert.equal(instances.size,1);w.testUI.disposeCharts();dom.window.close();
});

test('Login gates workspace and sales UI hides unauthorized features; logout clears private state',async()=>{
  const dom=environment(source('index.html')),w=dom.window,d=w.document;
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.echarts={getInstanceByDom:()=>null};
  let loggedIn=false;
  const user={id:'sales',role_id:'sales',name:'销售同事',role_name:'销售专员',policy:{tables:{customers:['id','name'],products:['id','name'],orders:['id','customer_id']},commands:['create_order'],scope:'customers'}};
  w.fetch=async(url,options={})=>{
    const p=String(url).replace('/api','');
    let data={},status=200;
    if(p==='/auth/login')loggedIn=true;
    else if(p==='/auth/logout')loggedIn=false;
    else if(!loggedIn){status=401;data={detail:'请登录'};}
    else if(p==='/bootstrap')data={user,token:'csrf',erp_status:'ok',model:'test',key_configured:true,commands:{create_order:{description:'创建订单',schema:{properties:{}}}}};
    else if(p==='/skills')data=[{id:'sales-review',name:'销售分析',description:'负责订单分析',version:'1',enabled:true,steps:[],inputs:{}}];
    else if(p==='/dashboard')data={cards:[{label:'待交付订单',value:2,unit:'单'}],sections:[]};
    else if(p==='/query')data={columns:['id','customer_id'],rows:[{id:'SO0013',customer_id:'C001'}]};
    else if(p==='/sessions')data=[];
    else throw new Error('Unexpected path '+p);
    return {ok:status===200,status,json:async()=>data};
  };
  w.eval(source('app.js')+'\nwindow.accessTest={navigate,showLogin};');
  await new Promise(r=>setTimeout(r,20));
  assert.equal(d.querySelector('#login-screen').hidden,false);
  assert.ok([...d.querySelectorAll('[data-shell]')].every(n=>n.hidden));
  d.querySelector('#login-username').value='sales';d.querySelector('#login-password').value='test-password';
  d.querySelector('#login-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
  for(let i=0;i<30&&d.querySelector('#login-screen').hidden===false;i++)await new Promise(r=>setTimeout(r,5));
  assert.equal(d.querySelector('#login-screen').hidden,true);
  assert.equal(d.querySelector('[data-page="admin"]').hidden,true);
  assert.equal(d.querySelector('#shutdown-top').hidden,true);
  assert.equal(d.querySelector('#shutdown').hidden,true);
  await w.accessTest.navigate('business');
  assert.deepEqual([...d.querySelectorAll('[data-entity]')].map(n=>n.dataset.entity).sort(),['customers','orders','products']);
  assert.ok(d.querySelector('#new-command'));
  await w.accessTest.navigate('skills');
  assert.equal(d.querySelector('#add-skill'),null);
  assert.equal(d.querySelector('[data-edit-skill]'),null);
  assert.equal(d.querySelector('[data-skill-toggle]'),null);
  assert.ok(d.querySelector('[data-use-skill]'));
  await w.accessTest.navigate('admin');
  assert.equal(d.querySelector('#page-title').textContent,'经营总览');
  d.querySelector('#logout').click();
  for(let i=0;i<30&&d.querySelector('#login-screen').hidden;i++)await new Promise(r=>setTimeout(r,5));
  assert.equal(d.querySelector('#login-screen').hidden,false);
  assert.equal(d.querySelector('#page').innerHTML,'');
  assert.equal(d.querySelector('#identity').textContent,'');
  dom.window.close();
});
