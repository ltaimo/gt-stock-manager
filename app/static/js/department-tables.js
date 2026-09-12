function syncReportChoices(root) {
  root.querySelectorAll('[data-fixed-options]').forEach(cell=>{
    let options;try{options=JSON.parse(cell.dataset.fixedOptions);}catch(_){return;}
    if(!options.length)return;
    let select=cell.previousElementSibling;
    if(!select?.hasAttribute('data-fixed-select')){
      select=document.createElement('select');select.dataset.fixedSelect='';
      select.setAttribute('aria-label',cell.getAttribute('aria-label')||cell.closest('label')?.childNodes[0]?.textContent||'Selecionar opção');
      for(const [value,label] of [['','Selecionar…'],...options.map((v,i)=>[String(i),v]),['other','Outro valor…']]){const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);}
      cell.before(select);
      select.addEventListener('change',()=>{
        const other=select.value==='other';cell.hidden=!other;
        if(!other)cell.value=select.value===''?'':options[Number(select.value)];
        else{cell.value='';cell.focus();}
        cell.dispatchEvent(new Event('input',{bubbles:true}));
      });
    }
    const index=options.indexOf(cell.value);
    select.value=index>=0?String(index):(cell.value?'other':'');cell.hidden=select.value!=='other';
  });
}
function parseReportTsv(text) {
  const rows = []; let row = [], value = '', quoted = false;
  text = text.replace(/\r\n?/g, '\n');
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"' && (quoted || !value)) {
      if (quoted && text[i + 1] === '"') { value += '"'; i++; }
      else quoted = !quoted;
    } else if (!quoted && (ch === '\t' || ch === '\n')) {
      row.push(value); value = '';
      if (ch === '\n') { rows.push(row); row = []; }
    } else value += ch;
  }
  if (quoted) throw new Error('Texto com aspas incompletas.');
  if (value || row.length) { row.push(value); rows.push(row); }
  return rows;
}
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form[data-department-draft]').forEach(form => {
    const storage = form.elements.namedItem('structured_tables');
    const editors = [...form.querySelectorAll('[data-report-table]')];
    const persist = () => {
      const data = {};
      editors.forEach(editor => {
        const rows = [...editor.querySelector('tbody').rows].map(row => [...row.querySelectorAll('textarea')].map(cell => cell.value));
        const note = editor.querySelector('[data-table-note]').value;
        data[editor.dataset.reportTable] = {rows, note};
      });
      storage.value = JSON.stringify(data);
    };
    const changed = () => { persist(); storage.dispatchEvent(new Event('input', {bubbles:true})); };
    const add = (editor, values=[]) => {
      const body = editor.querySelector('tbody');
      if (body.rows.length >= 150) { editor.querySelector('[data-table-message]').textContent = 'Limite de 150 linhas por tabela.'; return; }
      const row = editor.querySelector('template').content.firstElementChild.cloneNode(true);
      row.querySelectorAll('textarea').forEach((cell,i) => cell.value = values[i] || '');
      body.append(row); return row;
    };
    const restore = () => {
      let data; try { data = JSON.parse(storage.value || '{}'); } catch (_) { return; }
      editors.forEach(editor => {
        const value = data[editor.dataset.reportTable] || {};
        editor.querySelector('tbody').replaceChildren();
        (value.rows?.length ? value.rows : [[]]).forEach(row => add(editor, row));
        editor.querySelector('[data-table-note]').value = value.note || '';
        if (value.rows?.some(row => row.some(Boolean)) || value.note) editor.open = true;
      });
      syncReportChoices(form);
    };
    editors.forEach(editor => {
      editor.addEventListener('input', persist);
      editor.addEventListener('click', event => {
        if (event.target.closest('[data-add-row]')) { const row=add(editor); syncReportChoices(editor); row?.querySelector('textarea:not([hidden]),select').focus(); changed(); }
        if (event.target.closest('[data-remove-row]')) { event.target.closest('tr').remove(); changed(); }
      });
      editor.addEventListener('paste', event => {
        const cell = event.target.closest('tbody textarea') || event.target.closest('tbody select[data-fixed-select]')?.nextElementSibling;
        const text = event.clipboardData?.getData('text/plain');
        if (!cell || !text?.includes('\t')) return;
        event.preventDefault();
        let lines;
        try { lines = parseReportTsv(text); } catch (_) { editor.querySelector('[data-table-message]').textContent = 'Não foi possível interpretar as células. Verifique as aspas; nenhum dado foi colado.'; return; }
        const body = editor.querySelector('tbody');
        const ri = [...body.rows].indexOf(cell.closest('tr'));
        const ci = [...cell.closest('tr').querySelectorAll('textarea')].indexOf(cell);
        const count = cell.closest('tr').querySelectorAll('textarea').length;
        if (ri + lines.length > 150 || lines.some(row => row.length + ci > count || row.some(value => value.length > 1000))) {
          editor.querySelector('[data-table-message]').textContent = 'As células não cabem na tabela. Verifique o número de colunas e o limite de 150 linhas; nenhum dado foi colado.'; return;
        }
        while (body.rows.length < ri + lines.length) add(editor);
        lines.forEach((row,i) => row.forEach((value,j) => { body.rows[ri+i].querySelectorAll('textarea')[ci+j].value=value; }));
        syncReportChoices(editor);
        editor.querySelector('[data-table-message]').textContent = `${lines.length} linha(s) colada(s). Confira os cabeçalhos antes de submeter.`;
        changed();
      });
    });
    form.addEventListener('report-tables:restore', restore);
    restore();
  });
});
