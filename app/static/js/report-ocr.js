import * as pdfjs from '/static/vendor/ocr/pdf.mjs';
pdfjs.GlobalWorkerOptions.workerSrc='/static/vendor/ocr/pdf.worker.mjs';
const panel=document.querySelector('[data-report-ocr]');
if(panel){
  const button=panel.querySelector('[data-ocr-start]'), cancel=panel.querySelector('[data-ocr-cancel]'), status=panel.querySelector('[data-ocr-status]'), output=panel.querySelector('[data-ocr-output]');
  let stopped=false,worker=null,documentTask=null;
  const key=`gtims:ocr:${panel.dataset.user}:${panel.dataset.source}`;
  try { output.value=localStorage.getItem(key)||output.value; } catch(_){}
  cancel.addEventListener('click',()=>{stopped=true;status.textContent='A cancelar o reconhecimento…';worker?.terminate();documentTask?.destroy();});
  button.addEventListener('click',async()=>{
    stopped=false;button.disabled=true;cancel.hidden=false;let doc;
    try{
      status.textContent='A preparar o PDF e o reconhecimento em português…';
      const response=await fetch(panel.dataset.original,{credentials:'same-origin'});
      if(!response.ok||response.redirected)throw Error('Inicie sessão novamente para ler o original.');
      documentTask=pdfjs.getDocument({data:new Uint8Array(await response.arrayBuffer()),isEvalSupported:false});
      doc=await documentTask.promise;
      if(doc.numPages>100)throw Error('Limite de 100 páginas por documento.');
      const parts=[];
      for(let i=1;i<=doc.numPages;i++){
        if(stopped)throw Error('OCR cancelado. O original foi preservado.');
        status.textContent=`A ler página ${i} de ${doc.numPages}…`;
        const page=await doc.getPage(i), content=await page.getTextContent();
        let text=content.items.map(item=>item.str+(item.hasEOL?'\n':' ')).join('');
        if(text.replace(/\s/g,'').length<40){
          if(!worker)worker=await Tesseract.createWorker('por',1,{workerPath:'/static/vendor/ocr/worker.min.js?v=2',corePath:'/static/vendor/ocr/tesseract-core-lstm.wasm.js',langPath:'/static/vendor/ocr',workerBlobURL:false,errorHandler:error=>{status.textContent='Não foi possível iniciar o OCR: '+String(error);button.disabled=false;cancel.hidden=true;}});
          const base=page.getViewport({scale:1}),scale=Math.min(2.5,Math.sqrt(8000000/(base.width*base.height)));
          const viewport=page.getViewport({scale}),canvas=document.createElement('canvas');canvas.width=Math.ceil(viewport.width);canvas.height=Math.ceil(viewport.height);
          await page.render({canvasContext:canvas.getContext('2d'),viewport}).promise;
          const result=await worker.recognize(canvas);text=result.data.text;canvas.width=canvas.height=0;
        }
        parts.push(`Página ${i}\n${text}`);page.cleanup();
        output.value=parts.join('\n\n');
        if(output.value.length>500000)throw Error('O texto excede o limite. Divida o documento.');
        try{localStorage.setItem(key,output.value);}catch(_){}
      }
      if(stopped)throw Error('OCR cancelado.');
      const body=new FormData();body.set('text',output.value);body.set('pages',String(doc.numPages));body.set('revision',document.querySelector('input[name="revision"]').value);
      const saved=await fetch(panel.dataset.save,{method:'POST',credentials:'same-origin',body,headers:{Accept:'application/json'}});
      if(saved.redirected||saved.status===401)throw Error('Sessão expirada. O texto reconhecido ficou neste navegador.');
      const result=await saved.json();if(!saved.ok)throw Error(result.detail||'Não foi possível guardar o OCR.');
      document.querySelector('input[name="revision"]').value=result.revision;
      status.textContent='Texto reconhecido e guardado. Confira o original e os indicadores antes de validar. Reabra o documento para ver as sugestões.';
    }catch(error){status.textContent=stopped?'OCR cancelado. O original foi preservado.':error.message;}
    finally{await worker?.terminate().catch(()=>{});worker=null;await doc?.destroy().catch(()=>{});button.disabled=false;cancel.hidden=true;}
  });
  if(panel.dataset.auto==='1')button.click();
}
