/* Shared rendering for chat and the report studio. No model-generated chart code. */
(function(root) {
  'use strict';
  function markdown(text) {
    const html=root.marked.parse(String(text ?? ''),{gfm:true,breaks:true,async:false});
    const clean=root.DOMPurify.sanitize(html,{
      ALLOWED_TAGS:['p','br','h1','h2','h3','h4','h5','h6','strong','em','del','ul','ol','li','blockquote','pre','code','table','thead','tbody','tr','th','td','a','hr','input'],
      ALLOWED_ATTR:['href','title','class','start','align','type','checked','disabled'],
      ALLOW_DATA_ATTR:false,ALLOW_ARIA_ATTR:false
    });
    const template=root.document.createElement('template');template.innerHTML=clean;
    template.content.querySelectorAll('a').forEach(a=>{
      const href=a.getAttribute('href') || '';
      if(!/^(https?:\/\/|mailto:|\/(?!\/)|#)/i.test(href))a.removeAttribute('href');
      else if(/^https?:\/\//i.test(href)){a.target='_blank';a.rel='noopener noreferrer';}
    });
    template.content.querySelectorAll('input').forEach(input=>{input.type='checkbox';input.disabled=true;});
    template.content.querySelectorAll('table').forEach(table=>{
      const wrapper=root.document.createElement('div');wrapper.className='table-wrap';table.replaceWith(wrapper);wrapper.appendChild(table);
    });
    return template.innerHTML;
  }
  // Recover artifacts from every turn, and only from successful create_report calls.
  function chatEntries(messages) {
    const entries=[],calls=new Map(),reports=new Set();
    for(const message of messages){
      const body=message.body || message;
      if(body.role==='assistant')for(const call of body.tool_calls || [])calls.set(call.id,call.function?.name);
      if(['user','assistant'].includes(body.role)&&body.content)entries.push({kind:'message',role:body.role,text:body.content});
      if(body.role!=='tool'||calls.get(body.tool_call_id)!=='create_report')continue;
      try{
        const output=JSON.parse(body.content),report=output.result;
        if(output.ok&&report?.id&&Array.isArray(report.data?.rows)&&!reports.has(report.id)){entries.push({kind:'report',report});reports.add(report.id);}
      }catch{/* Failed/malformed tool results are not charts. */}
    }
    return entries;
  }
  function withAxes(report,chartType=report.chart_type){
    const data=report.data?.rows || report.rows || [],columns=report.data?.columns || Object.keys(data[0] || {});
    const numeric=columns.filter(c=>data.length&&data.every(r=>typeof r[c]==='number'&&Number.isFinite(r[c])));
    const x=columns.includes(report.x)?report.x:(columns.find(c=>!numeric.includes(c)) || columns[0] || '');
    const y=(report.y || []).filter(c=>numeric.includes(c));
    return {...report,chart_type:chartType,x,y:y.length?y:numeric.filter(c=>c!==x).slice(0,8)};
  }
  function viewTypes(report){
    const spec=withAxes(report),types=['table'];
    if(spec.x&&spec.y.length){
      types.push('bar','pie','line','area');
      if((spec.data?.rows || spec.rows || []).every(r=>typeof r[spec.x]==='number'))types.push('scatter');
      if(spec.group)types.push('pivot','heatmap');
    }
    return [...new Set([report.chart_type,...types])];
  }
  function reportView(report){
    const {chart_type:type,x,y=[],group}=report,data=report.data?.rows || report.rows || [];
    const columns=report.data?.columns || Object.keys(data[0] || {});
    if(!data.length)return {kind:'empty'};
    if(type==='table')return {kind:'table',rows:data,columns};
    if(!x||!columns.includes(x)||!y.length||y.some(c=>!columns.includes(c)))throw new Error('请选择有效的维度与数值列');
    if(data.some(r=>y.some(c=>typeof r[c]!=='number'||!Number.isFinite(r[c]))))throw new Error('数值列必须全部为数字');
    const option={color:['#528a72','#b3c58d','#d4ae77','#8eacb9','#bc9fb6','#b8c7bd'],aria:{enabled:true},tooltip:{trigger:'axis',renderMode:'richText'},legend:{type:'scroll',bottom:0,textStyle:{fontSize:11,color:'#647a63'}},grid:{top:25,right:20,bottom:65,left:20,containLabel:true},xAxis:{type:'category',data:data.map(r=>r[x]),axisLabel:{fontSize:10,color:'#61765b',width:100,overflow:'truncate'},axisLine:{lineStyle:{color:'#e0e9d9'}},axisTick:{show:false}},yAxis:{type:'value',axisLabel:{fontSize:10,color:'#61765b'},splitLine:{lineStyle:{color:'#eef3e8'}}}};
    if(type==='pivot'||type==='heatmap'){
      if(!columns.includes(group))throw new Error('请选择有效的分组列');
      const xs=[...new Set(data.map(r=>String(r[x])))],gs=[...new Set(data.map(r=>String(r[group])))];
      const sum=(xx,gg)=>data.filter(r=>String(r[x])===xx&&String(r[group])===gg).reduce((n,r)=>n+r[y[0]],0);
      if(type==='pivot')return {kind:'table',columns:['维度',...gs.map(g=>'分组 · '+g)],rows:xs.map(xx=>Object.fromEntries([['维度',xx],...gs.map(g=>['分组 · '+g,sum(xx,g)])]))};
      const values=xs.flatMap((xx,i)=>gs.map((gg,j)=>[i,j,sum(xx,gg)]));option.xAxis.data=xs;option.yAxis={type:'category',data:gs};option.tooltip={position:'top',renderMode:'richText'};option.visualMap={min:Math.min(0,...values.map(v=>v[2])),max:Math.max(1,...values.map(v=>v[2])),calculable:true,orient:'horizontal',left:'center',bottom:0,inRange:{color:['#edf4df','#2e7553']}};option.series=[{name:y[0],type:'heatmap',data:values,label:{show:true}}];delete option.legend;
    }else if(type==='pie'){
      if(data.some(r=>r[y[0]]<0))throw new Error('饼图不支持负数，请切换为柱状图');
      delete option.xAxis;delete option.yAxis;option.tooltip={trigger:'item',renderMode:'richText'};option.series=[{name:y[0],type:'pie',radius:['32%','64%'],center:['50%','43%'],data:data.map(r=>({name:String(r[x]),value:r[y[0]]})),label:{fontSize:11,formatter:'{b}: {d}%',overflow:'break'}}];
    }else if(type==='scatter'){
      if(data.some(r=>typeof r[x]!=='number'))throw new Error('散点图X轴也必须是数字');
      option.xAxis={type:'value',name:x};option.tooltip={trigger:'item',renderMode:'richText'};option.series=y.map(c=>({name:c,type:'scatter',symbolSize:13,data:data.map(r=>[r[x],r[c]])}));
    }else if(['bar','line','area'].includes(type))option.series=y.map(c=>({name:c,type:type==='area'?'line':type,smooth:type!=='bar',barMaxWidth:48,areaStyle:type==='area'?{opacity:.15}:undefined,itemStyle:{borderRadius:type==='bar'?[5,5,0,0]:0},data:data.map(r=>r[c])}));
    else throw new Error('不支持的图表类型');
    return {kind:'chart',option};
  }
  root.DemoUI={markdown,chatEntries,withAxes,viewTypes,reportView};
})(typeof window!=='undefined'?window:globalThis);
