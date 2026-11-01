/* Human form verification. Tokens remain in memory and are never logged or stored. */
(function () {
    const message='A verificação de segurança não respondeu. Seus dados foram preservados; tente novamente.';
    const widgets=new WeakMap();let sdk=null;
    function timeout(task, ms) {let timer;return Promise.race([task,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(message)),ms);})]).finally(()=>clearTimeout(timer));}
    async function load() {
        if(!sdk)sdk=new Promise((resolve,reject)=>{
            const script=document.createElement('script');script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
            script.async=true;script.defer=true;script.dataset.turnstileSdk='true';
            script.onload=()=>typeof window.turnstile?.render==='function'?resolve():reject(Error(message));
            script.onerror=()=>reject(Error(message));document.head.append(script);
        });
        try{await timeout(sdk,15000);}catch{document.querySelector('[data-turnstile-sdk]')?.remove();sdk=null;throw Error(message);}
    }
    window.DatanoTurnstile={
        async token(form,config){
            if(!config?.siteKey)throw Error(message);await load();let state=widgets.get(form);
            if(!state){
                const container=document.createElement('div');container.setAttribute('role','group');container.setAttribute('aria-label','Verificação de segurança');form.append(container);
                state={id:null,token:null,error:false};widgets.set(form,state);
                const invalidate=()=>{state.token=null;state.error=true;state.reject?.(Error(message));state.resolve=state.reject=null;};
                try{state.id=window.turnstile.render(container,{sitekey:config.siteKey,action:'login',size:container.getBoundingClientRect().width<300?'compact':'flexible',language:'pt-br','response-field':false,
                    callback:token=>{state.token=token;state.error=false;state.resolve?.(token);state.resolve=state.reject=null;},
                    'expired-callback':invalidate,'error-callback':invalidate,'timeout-callback':invalidate});}
                catch{container.remove();widgets.delete(form);throw Error(message);}
            }
            try{
                if(state.error)throw Error(message);
                const token=state.token||await timeout(new Promise((resolve,reject)=>{state.resolve=resolve;state.reject=reject;}),120000);
                if(typeof token!=='string'||!token||token.length>2048)throw Error(message);state.token=null;return token;
            }finally{state.resolve=state.reject=null;}
        },
        reset(form){const state=widgets.get(form);if(!state)return;state.token=null;state.error=false;state.resolve=state.reject=null;try{window.turnstile?.reset(state.id);}catch{}},
    };
})();

(function(){
 const form=document.querySelector('form[data-turnstile-login]');if(!form)return;
 const button=form.querySelector('button[type="submit"]');
 const error=document.createElement('p');error.setAttribute('role','alert');form.append(error);
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(button.disabled)return;button.disabled=true;error.textContent='Confirmando esta tentativa com segurança…';
  try{
   const token=await window.DatanoTurnstile.token(form,{siteKey:form.dataset.sitekey});
   const body=new URLSearchParams(new FormData(form));body.set('cf-turnstile-response',token);
   const response=await fetch(form.action,{method:'POST',headers:{'Accept':'application/json'},body});
   const result=await response.json().catch(()=>{throw Error('Não foi possível conectar. Seus dados foram preservados; tente novamente.');});if(result.csrf&&form.elements.csrf)form.elements.csrf.value=result.csrf;
   if(!response.ok)throw Error(result.error||result.detail||'Não foi possível entrar. Seus dados foram preservados; tente novamente.');
   if(typeof result.redirect!=='string'||!result.redirect.startsWith('/')||result.redirect.startsWith('//'))throw Error('Não foi possível continuar.');
   location.assign(result.redirect);
  }catch(failure){error.textContent=failure instanceof TypeError?'Não foi possível conectar. Seus dados foram preservados; tente novamente.':failure.message||'Não foi possível continuar.';}
  finally{window.DatanoTurnstile.reset(form);button.disabled=false;}
 });
})();
