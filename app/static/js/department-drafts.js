/* Local recovery is immediate; server writes are serialized and debounced. */
function initDepartmentDrafts() {
  document.querySelectorAll('form[data-department-draft]').forEach((form) => {
    const prefix = `gtims:department-draft:${form.dataset.draftUser}:${form.dataset.draftDepartment}:`;
    let key = prefix + form.dataset.draftId;
    try {
      const active = localStorage.getItem(prefix + 'active');
      if (form.dataset.draftId === 'new' && active?.startsWith(prefix)) key = active;
    } catch (_) { /* Server drafts do not require browser storage. */ }
    const message = form.querySelector('[data-draft-status]');
    const fields = () => Array.from(form.elements).filter(f => f.name && !['submit', 'button'].includes(f.type));
    let dirty = false, timer, pending = Promise.resolve(), submitting = false, complete = false, conflict = false, touched = false;
    const say = (name) => { message.textContent = form.dataset[name]; };
    const snapshot = () => Object.fromEntries(fields().map(f => [f.name, f.value]));
    const persist = () => {
      if (complete || conflict || !touched) return;
      try {
        localStorage.setItem(key, JSON.stringify({data: snapshot(), savedAt: Date.now()}));
        localStorage.setItem(prefix + 'active', key);
        return true;
      }
      catch (_) { say('msgUnavailable'); }
    };
    const restore = (data) => { fields().forEach(f => {
      if (f.name !== 'department_key' && Object.hasOwn(data, f.name)) f.value = data[f.name];
    }); form.dispatchEvent(new Event('report-tables:restore')); };
    const resolveConflict = (data, version) => {
      conflict = true;
      fields().filter(f => f.type !== 'hidden').forEach(f => { f.readOnly = true; });
      say('msgConflict');
      const actions = document.createElement('div');
      actions.className = 'actions';
      const recover = document.createElement('button');
      recover.type = 'button';
      recover.textContent = form.dataset.msgRecover;
      recover.addEventListener('click', () => {
        restore(data);
        form.elements.namedItem('draft_version').value = version;
        conflict = false;
        fields().filter(f => f.type !== 'hidden').forEach(f => { f.readOnly = false; });
        actions.remove();
        changed();
      });
      const server = document.createElement('button');
      server.type = 'button';
      server.textContent = form.dataset.msgUseServer;
      server.addEventListener('click', () => {
        const id = data.draft_id || form.elements.namedItem('draft_id').value;
        try { localStorage.removeItem(key); } catch (_) { /* Reload still works. */ }
        complete = true;
        window.location.assign(`/operacoes-internas/relatorios-departamentais?department=${encodeURIComponent(form.dataset.draftDepartment)}&draft_id=${encodeURIComponent(id)}`);
      });
      actions.append(recover, server);
      message.after(actions);
    };
    let initialConflict;
    try {
      const saved = JSON.parse(localStorage.getItem(key) || 'null');
      if (saved?.data) {
        const version = form.elements.namedItem('draft_version').value;
        if (form.dataset.draftId !== 'new' && version && saved.data.draft_version !== version) initialConflict = {data: saved.data, version};
        else {
          restore(saved.data);
          dirty = touched = true;
          say('msgLocal');
        }
      }
    } catch (_) { /* Server draft remains usable if browser storage is unavailable. */ }

    async function write(status, endpoint) {
      const data = new FormData(form);
      data.set('status', status);
      let response;
      try { response = await fetch(endpoint, {method: 'POST', body: data, credentials: 'same-origin', headers: {Accept: 'application/json'}}); }
      catch (error) { say('msgError'); throw error; }
      if (response.status === 401 || response.redirected) { say('msgExpired'); throw new Error('session'); }
      if (!response.ok) {
        let detail, errorData;
        try { errorData = await response.json(); detail = errorData.detail; } catch (_) { /* HTML errors use the general message. */ }
        if (typeof detail === 'string') message.textContent = detail;
        else say('msgError');
        if (response.status === 409) {
          if (errorData?.version) resolveConflict(snapshot(), errorData.version);
          else {
            conflict = true;
            try { if (localStorage.getItem(prefix + 'active') === key) localStorage.removeItem(prefix + 'active'); } catch (_) { /* Preserve recovery copy. */ }
          }
        }
        throw new Error('save');
      }
      const saved = await response.json();
      form.elements.namedItem('draft_id').value = saved.id;
      form.elements.namedItem('draft_version').value = saved.version;
      const previousKey = key;
      key = prefix + saved.id;
      const stored = persist();
      if (stored && previousKey !== key) {
        try { localStorage.removeItem(previousKey); } catch (_) { /* Canonical copy is already saved. */ }
      }
      return saved;
    }
    const sync = () => {
      clearTimeout(timer);
      if (!dirty || submitting || complete || conflict) return pending;
      dirty = false;
      pending = pending.catch(() => {}).then(async () => {
        try {
          await write('Draft', '/operacoes-internas/relatorios-departamentais/rascunho');
          if (!dirty) say('msgSaved');
        } catch (_) { dirty = true; }
      });
      return pending;
    };
    const changed = () => {
      if (complete || submitting || conflict) return;
      dirty = touched = true;
      say('msgLocal');
      persist();
      clearTimeout(timer);
      timer = setTimeout(sync, 1200);
    };
    form.addEventListener('input', changed);
    form.addEventListener('change', changed);
    window.addEventListener('pagehide', persist);
    window.addEventListener('gtims:before-logout', persist);
    window.addEventListener('online', sync);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { persist(); sync(); }
    });
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (submitting || conflict) return;
      submitting = true;
      form.querySelectorAll('[data-report-table]').forEach(editor => { editor.inert = true; });
      clearTimeout(timer);
      persist();
      const status = event.submitter?.value === 'Draft' ? 'Draft' : 'Submitted';
      const buttons = form.querySelectorAll('button[type="submit"], button[name="status"]');
      buttons.forEach(b => b.disabled = true);
      const editable = fields().filter(f => f.type !== 'hidden');
      editable.forEach(f => { f.readOnly = true; });
      try {
        await pending.catch(() => {});
        await write(status, form.action);
        complete = true;
        try {
          localStorage.removeItem(key);
          if (localStorage.getItem(prefix + 'active') === key) localStorage.removeItem(prefix + 'active');
        } catch (_) { /* Save already succeeded. */ }
        window.location.assign(`/operacoes-internas/relatorios-departamentais?department=${encodeURIComponent(form.dataset.draftDepartment)}`);
      } catch (_) {
        submitting = false;
        form.querySelectorAll('[data-report-table]').forEach(editor => { editor.inert = false; });
        buttons.forEach(b => b.disabled = false);
        editable.forEach(f => { f.readOnly = conflict; });
      }
    });
    if (initialConflict) resolveConflict(initialConflict.data, initialConflict.version);
    if (dirty) timer = setTimeout(sync, 1200);
  });
}
document.addEventListener('DOMContentLoaded', initDepartmentDrafts);
