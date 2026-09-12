document.addEventListener('DOMContentLoaded',()=>{
  const form=document.querySelector('[data-schema-editor]');if(!form)return;
  const tables=form.querySelector('[data-schema-tables]');
  const reindex=()=>[...tables.children].forEach((table,i)=>{
    for(const attr of ['key','title','section'])table.querySelector(`[data-${attr}]`).name=`table_${i}_${attr}`;
    [...table.querySelector('[data-schema-columns]').children].forEach((col,j)=>{
      col.querySelector('[data-label]').name=`col_${i}_${j}_label`;
      col.querySelector('[data-choices]').name=`col_${i}_${j}_choices`;
    });
  });
  form.addEventListener('click',e=>{
    const table=e.target.closest('[data-schema-table]');
    if(e.target.closest('[data-remove-column]'))e.target.closest('[data-schema-column]').remove();
    if(e.target.closest('[data-remove-table]'))table.remove();
    if(e.target.closest('[data-add-column]')){
      const cols=table.querySelector('[data-schema-columns]');
      if(cols.children.length>=12){form.querySelector('[data-schema-status]').textContent='Limite de 12 colunas por tabela.';return;}
      cols.append(form.querySelector('[data-new-column]').content.cloneNode(true));
    }
    if(e.target.closest('[data-add-table]')){
      if(tables.children.length>=16){form.querySelector('[data-schema-status]').textContent='Limite de 16 tabelas.';return;}
      tables.append(form.querySelector('[data-new-table]').content.cloneNode(true));
      tables.lastElementChild.querySelector('[data-schema-columns]').append(form.querySelector('[data-new-column]').content.cloneNode(true));
    }
    reindex();
  });reindex();const ready=document.createElement('input');ready.type='hidden';ready.name='schema_ready';ready.value='1';form.append(ready);
});
