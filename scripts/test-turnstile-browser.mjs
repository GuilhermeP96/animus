// Offline UI qualification: real login UI/helper, provider and API transport fixtures.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../',import.meta.url));
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.TURNSTILE_PLAYWRIGHT_PACKAGE||'@playwright/test');
const html=execFileSync(process.env.ANIMUS_TEST_PYTHON||'python3',['-c',"import sys;from jinja2 import Environment;print(Environment(autoescape=True).from_string(open(sys.argv[1]).read()).render(error=None,turnstile={'siteKey':'fixture-public'}))",root+'animus/server/templates/login.html'],{encoding:'utf8'});
const assets={'/login-security.js':readFileSync(root+'animus/server/static/login-security.js','utf8')};
const entry='/login',endpoint='/login',formSelector='form[data-turnstile-login]',userSelector='#username',passwordSelector='#password',tokenField='cf-turnstile-response',native=true;
const base='http://127.0.0.1:4199';
const browser=await chromium.launch({headless:true});
try{
 for(const scenario of ['rejected','expiry','load']){
  const page=await browser.newPage({viewport:{width:390,height:844}});let sdkRequests=0;const attempts=[];
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.hostname==='challenges.cloudflare.com'){
    if(scenario==='load'&&sdkRequests++===0)return route.abort('failed');
    return route.fulfill({contentType:'application/javascript',body:`
      let options,expired=false;window.fixtureResets=0;window.fixtureReadyCalls=0;
      function complete(){setTimeout(()=>options.callback('fixture-'+crypto.randomUUID()),10);}
      window.turnstile={ready:()=>{window.fixtureReadyCalls++;throw Error('3857: ready is unavailable for an async/defer SDK');},render:(container,settings)=>{options=settings;if(${scenario==='expiry'}&&!expired){expired=true;setTimeout(settings['expired-callback'],10);}else complete();return 'fixture-widget';},reset:()=>{window.fixtureResets++;complete();}};
    `});
   }
   if(url.origin!==base)return route.abort('blockedbyclient');
   if(assets[url.pathname])return route.fulfill({contentType:'application/javascript',body:assets[url.pathname]});
   if(url.pathname==='/api/auth/config')return route.fulfill({contentType:'application/json',body:JSON.stringify({enabled:true,siteKey:'fixture-public'})});
   if(url.pathname==='/api/auth/me')return route.fulfill({status:401,contentType:'application/json',body:'{}'});
   if(url.pathname===endpoint&&route.request().method()==='POST'){
    const data=route.request().headers()['content-type'].includes('application/json')?route.request().postDataJSON():Object.fromEntries(new URLSearchParams(route.request().postData()));
    attempts.push(data);const rejected=scenario==='rejected'&&attempts.length===1;
    return route.fulfill({status:rejected?403:200,contentType:'application/json',body:JSON.stringify(rejected?{error:'Seus dados foram preservados; tente novamente.',detail:'Seus dados foram preservados; tente novamente.',csrf:'fixture-fresh-csrf'}:{username:'fixture',role:'user',redirect:'/done'})});
   }
   if(url.pathname==='/done')return route.fulfill({contentType:'text/html',body:'<p>Authorized fixture</p>'});
   return route.fulfill({contentType:'text/html',body:html});
  });
  await page.goto(base+entry);const form=page.locator(formSelector);
  await form.locator(userSelector).fill('fixture');await form.locator(passwordSelector).fill('fixture-password-12');
  await form.locator('button[type="submit"]').click();
  await page.waitForFunction(()=>document.body.textContent.includes('preservados'));
  assert.equal(await form.locator(userSelector).inputValue(),'fixture');assert.equal(await form.locator(passwordSelector).inputValue(),'fixture-password-12');
  assert.equal(attempts.length,scenario==='rejected'?1:0);
  assert.equal(await page.evaluate(()=>window.fixtureReadyCalls??0),0);
  const storage=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));assert(!storage.includes('fixture-password-12'));
  await form.locator('button[type="submit"]').click();
  if(native)await page.waitForURL('**/done');else await page.waitForFunction(()=>document.querySelector('#login-screen').hidden);
  assert.equal(attempts.length,scenario==='rejected'?2:1);assert(attempts.every(attempt=>typeof attempt[tokenField]==='string'));
  if(attempts.length===2)assert.notEqual(attempts[0][tokenField],attempts[1][tokenField]);
  await page.close();console.log(JSON.stringify({scenario,passed:true,provider:'mocked',backend:'mocked',mobile_viewport:true}));
 }
}finally{await browser.close();}
