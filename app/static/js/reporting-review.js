/* Keep editable supplements recoverable; official sources stay on the server. */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-report-generator]').forEach(form => {
    const department=form.elements.namedItem('department'),period=form.elements.namedItem('period');
    const update=()=>{
      for(const option of period.options){
        const allowed=option.value==='daily' ? department.value==='consolidated' : option.value==='inspection' ? department.value==='it' : true;
        option.hidden=option.disabled=!allowed;
      }
      if(period.selectedOptions[0]?.disabled)period.value='weekly';
    };
    department.addEventListener('change',update);update();
  });
  const addMetric = () => {
    const body = document.querySelector('[data-metric-rows]');
    if (!body || body.rows.length >= 200) return;
    const index = body.rows.length, row = body.rows[index-1].cloneNode(true);
    row.querySelectorAll('[name]').forEach(field => {
      field.name = field.name.replace(/metric_\d+_/, `metric_${index}_`);
      field.value = '';
    });
    body.append(row);
  };
  document.querySelector('[data-add-metric]')?.addEventListener('click', addMetric);
  document.querySelectorAll('[data-report-review]').forEach(form => {
    const key = `gtims:report-review:${form.dataset.userId}:${form.dataset.reportId}`;
    const status = form.querySelector('[data-review-status]');
    const revision = form.elements.namedItem('revision');
    const fields = () => Array.from(form.elements).filter(f => f.name && f.type !== 'submit');
    const snapshot = () => Object.fromEntries(fields().map(f => [f.name, f.value]));
    let timer, pending = Promise.resolve(), blocked = false, submitting = false, touched = false, complete = false;
    const say = text => { status.textContent = text; };
    const persist = () => {
      if (!touched || complete || blocked) return;
      try { localStorage.setItem(key, JSON.stringify(snapshot())); }
      catch (_) { say('O navegador não permite guardar uma cópia local. Guarde o rascunho no sistema.'); }
    };
    const restore = data => {
      const indexes = Object.keys(data).map(k => /^metric_(\d+)_/.exec(k)).filter(Boolean).map(m => Number(m[1]));
      const body = document.querySelector('[data-metric-rows]');
      if (body && indexes.length) while (body.rows.length <= Math.max(...indexes) && body.rows.length < 200) addMetric();
      fields().forEach(f => { if (Object.hasOwn(data,f.name) && f.name!=='revision') f.value=data[f.name]; });
    };
    const write = async action => {
      const data = new FormData(form); data.set('action',action);
      let response;
      try { response = await fetch(form.getAttribute('action') || window.location.pathname,{method:'POST',credentials:'same-origin',body:data,headers:{Accept:'application/json'}}); }
      catch (error) { say('Sem ligação. A cópia local foi preservada.'); throw error; }
      if (response.redirected || response.status===401) { say('Sessão expirada. Inicie sessão para continuar este rascunho.'); throw new Error('session'); }
      const result = await response.json();
      if (!response.ok) {
        if (response.status===409) blocked=true;
        say(typeof result.detail==='string' ? result.detail : 'Não foi possível guardar. A cópia local foi preservada.');
        throw new Error('save');
      }
      revision.value=result.revision;
      document.querySelectorAll('[data-current-revision]').forEach(f => f.value=result.revision);
      persist(); say('Rascunho guardado automaticamente.'); return result;
    };
    const queue = () => {
      clearTimeout(timer);
      if (blocked || submitting || complete) return;
      pending=pending.catch(()=>{}).then(()=>write('Draft')).catch(()=>{});
    };
    const changed = () => {
      if (blocked || submitting) return;
      touched=true;persist();say('Alterações guardadas neste navegador.');clearTimeout(timer);timer=setTimeout(queue,1200);
    };
    try {
      const saved=JSON.parse(localStorage.getItem(key)||'null');
      if (saved) {
        if (saved.revision===revision.value) { restore(saved); changed(); }
        else {
          blocked=true;say('Existe uma cópia local diferente da versão do sistema. Escolha qual pretende continuar.');
          const actions=document.createElement('div');actions.className='actions';
          const local=document.createElement('button');local.type='button';local.textContent='Recuperar a minha cópia local';
          local.addEventListener('click',()=>{restore(saved);blocked=false;actions.remove();changed();});
          const server=document.createElement('button');server.type='button';server.textContent='Usar versão do sistema';
          server.addEventListener('click',()=>{localStorage.removeItem(key);blocked=false;actions.remove();say('Versão do sistema carregada.');});
          actions.append(local,server);status.after(actions);
        }
      }
    } catch (_) { /* The server draft is still available. */ }
    form.addEventListener('input',changed);form.addEventListener('change',changed);
    window.addEventListener('pagehide',persist);window.addEventListener('gtims:before-logout',persist);
    window.addEventListener('online',()=>{if(touched)queue();});
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(blocked||submitting)return;
      touched=true;persist();clearTimeout(timer);submitting=true;
      const action=event.submitter?.value||'Draft';
      const buttons=form.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
      try {
        await pending;
        if(blocked)throw new Error('conflict');
        await write(action);complete=true;
        try { localStorage.removeItem(key); } catch (_) { /* Server save already succeeded. */ }
        window.location.reload();
      } catch (_) {submitting=false;buttons.forEach(b=>b.disabled=false);}
    });
  });
});
