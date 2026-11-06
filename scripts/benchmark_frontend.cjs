const fs=require('node:fs');
const path=require('node:path');
const perf=require('node:perf_hooks').performance;
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
const dom=new JSDOM('',{runScripts:'outside-only'});
dom.window.eval(fs.readFileSync(path.join(root,'frontend/renderers.js'),'utf8'));
const makeReport=rows=>({chart_type:'heatmap',x:'x',y:['y'],group:'g',data:{columns:['x','g','y'],rows}});
const rows=Array.from({length:500},(_,i)=>({x:'X'+(i%100),g:'G'+(Math.floor(i/5)%100),y:i}));
const samples=[];
for(let i=0;i<3;i++){
  const start=perf.now();dom.window.DemoUI.reportView(makeReport(rows));samples.push(Math.round((perf.now()-start)*100)/100);
}
let large;
try{dom.window.DemoUI.reportView(makeReport(Array.from({length:500},(_,i)=>({x:i,g:i,y:1}))));large='ok';}
catch(error){large=error.message;}
const result={rows:500,cells:10000,samples_ms:samples,large_grid:large};
if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(result,null,2)+'\n');
console.log(result);dom.window.close();
