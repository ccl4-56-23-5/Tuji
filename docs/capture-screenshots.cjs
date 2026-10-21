/* Render 1.5.1 UI with public synthetic data; Node.js + Playwright + Microsoft Edge. */
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const repo = path.resolve(__dirname, '..');
const base = path.join(repo, 'sources/NefGpsTrack/1.5.1');
const scratch = path.join(repo, 'temp/readme-screenshots');
const imageDir = path.join(__dirname, 'images');
fs.mkdirSync(scratch, {recursive:true}); fs.mkdirSync(imageDir, {recursive:true});
let source = fs.readFileSync(path.join(base,'qa/ui-151.cjs'),'utf8');
source = source.replace("path.resolve(__dirname,'..')",JSON.stringify(base));
source = source.replace("path.join(__dirname,'fixture.json')",JSON.stringify(path.join(base,'qa/fixture.json')));
const start = source.indexOf(' const shot=(n,full)=>');
if(start<0)throw Error('Expected screenshot helper not found');
const end = source.indexOf('\n',start);
source = source.slice(0,start)+`
 const imageDir=${JSON.stringify(imageDir)};
 const selected={'recording':'android-recording','library':'android-library','viewer':'android-review','windows-pins':'windows-matching','windows-photos':'windows-results','windows-settings':'windows-settings','windows-library':'windows-library'};
 const shot=async(n)=>{
   if(!selected[n])return;
   const old=p.viewportSize(),pos=await p.evaluate(()=>({x:scrollX,y:scrollY}));
   if(n==='viewer')await p.evaluate(async()=>{qaCurve=null;await openRoute(1);});
   if(n.startsWith('windows-'))await p.setViewportSize({width:1440,height:1400});
   await p.evaluate(()=>scrollTo(0,0));await p.waitForTimeout(650);
   await p.screenshot({path:path.join(imageDir,selected[n]+'.png'),fullPage:false,animations:'disabled'});
   await p.setViewportSize(old);await p.evaluate(pos=>scrollTo(pos.x,pos.y),pos);await p.waitForTimeout(200);
 };`+source.slice(end);
source = source.replace("const shotOf=async(n,selector)=>p.locator(selector).screenshot({path:path.join(__dirname,'ui-151-'+n+'.png')});",'const shotOf=async()=>{};');
const filename=path.join(scratch,'capture.cjs');
const runner=new Module(filename,module);runner.filename=filename;runner.paths=Module._nodeModulePaths(scratch);runner._compile(source,filename);
