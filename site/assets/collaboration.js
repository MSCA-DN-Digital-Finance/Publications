'use strict';
(() => {
  const form=document.getElementById('collaboration-form');if(!form)return;
  const data=JSON.parse(document.getElementById('research-data').textContent);
  const split=value=>(value||'').split(';').map(v=>v.trim()).filter(Boolean);
  const papers=new Map(data.working_papers.map(p=>[p.id,p]));
  const people=new Map(data.people.filter(p=>p.candidate).map(p=>[p.number,p]));
  const requests=data.collaboration_requests||[],params=new URLSearchParams(location.search);
  const existing=requests.find(r=>r.id===params.get('request'));
  const paperSelect=form.elements.working_paper_id,irpSelect=form.elements.irp_numbers,message=form.elements.message,state=form.elements.status;
  const feedback=document.getElementById('request-feedback'),review=document.getElementById('request-review');
  let proposal;
  function option(select,value,label){const item=document.createElement('option');item.value=value;item.textContent=label;select.append(item);}
  for(const paper of papers.values())if(existing?.working_paper_id===paper.id||(paper.open_to_collaborate==='yes'&&!['paused','completed'].includes(paper.status)))option(paperSelect,paper.id,paper.title);
  for(const p of people.values())option(irpSelect,p.number,`IRP ${p.number} · ${p.candidate.name}`);
  if(existing){paperSelect.value=existing.working_paper_id;paperSelect.disabled=true;[...irpSelect.options].forEach(o=>o.selected=split(existing.irp_numbers).includes(o.value));irpSelect.disabled=true;message.value=existing.message;state.value=existing.status;document.getElementById('request-status-field').hidden=false;document.querySelector('h1').textContent='Update collaboration request';}
  else if(papers.has(params.get('paper')))paperSelect.value=params.get('paper');
  function sync(){
    const paper=papers.get(paperSelect.value);
    document.getElementById('paper-needs').textContent=paper?.collaboration_needs||'';
    const own=new Set(split(paper?.irp_numbers));
    const active=new Set(requests.filter(r=>r.id!==existing?.id&&r.working_paper_id===paper?.id&&['requested','accepted'].includes(r.status)).flatMap(r=>split(r.irp_numbers)));
    if(!existing)for(const option of irpSelect.options){option.disabled=own.has(option.value)||active.has(option.value);if(option.disabled)option.selected=false;}
    form.querySelector('[type="submit"]').disabled=!paper;
    if(!paper)feedback.textContent='No working papers are currently accepting collaboration requests.';
  }
  function invalidate(){proposal=null;review.hidden=true;feedback.textContent='';sync();}
  paperSelect.addEventListener('change',invalidate);irpSelect.addEventListener('change',invalidate);message.addEventListener('input',invalidate);state.addEventListener('change',invalidate);sync();
  form.addEventListener('submit',event=>{
    event.preventDefault();const numbers=existing?split(existing.irp_numbers):[...irpSelect.selectedOptions].filter(o=>!o.disabled).map(o=>o.value);
    if(!numbers.length){feedback.textContent='Choose at least one requesting IRP.';return;}
    const text=message.value.trim();if(!text){feedback.textContent='Describe how you would like to collaborate.';return;}
    const record={id:existing?.id||'request-'+crypto.randomUUID(),working_paper_id:paperSelect.value,irp_numbers:numbers.join(';'),message:text,status:existing?state.value:'requested',last_updated:new Date().toISOString().slice(0,10)};
    proposal={kind:'collaboration-request',action:existing?'update':'add',record};
    document.getElementById('request-json').textContent=JSON.stringify(proposal,null,2);
    document.getElementById('request-preview').textContent=numbers.map(n=>`IRP ${n} · ${people.get(n).candidate.name}`).join('; ')+' → '+papers.get(record.working_paper_id).title;
    const body='## Collaboration request\n\nPlease review the requesting IRPs and proposed status with the working paper authors before applying collaboration-approved.\n\n```json\n'+JSON.stringify(proposal,null,2)+'\n```';
    const url=data.config.repository+'/issues/new?'+new URLSearchParams({template:'collaboration-request.md',title:`[Collaboration ${proposal.action}] ${papers.get(record.working_paper_id).title}`,body});
    const link=document.getElementById('submit-request');link.href=url;link.hidden=url.length>7000;
    document.getElementById('request-too-long').hidden=url.length<=7000;
    document.getElementById('new-request-issue').href=data.config.repository+'/issues/new?template=collaboration-request.md';
    review.hidden=false;feedback.textContent='Request prepared. Review it and submit the GitHub issue; reviewed requests appear on the working paper card.';
    review.scrollIntoView({block:'start'});
  });
  document.getElementById('download-request').addEventListener('click',()=>{if(!proposal)return;const url=URL.createObjectURL(new Blob([JSON.stringify(proposal,null,2)+'\n'],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=proposal.record.id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  const key='digital-collaboration-draft';
  document.getElementById('save-request').addEventListener('click',()=>{try{localStorage.setItem(key,JSON.stringify({request_id:existing?.id||'',paper:paperSelect.value,irps:[...irpSelect.selectedOptions].map(o=>o.value),message:message.value,status:state.value}));feedback.textContent='Draft saved in this browser.';}catch{feedback.textContent='This browser could not save the draft.';}});
  document.getElementById('restore-request').addEventListener('click',()=>{try{const draft=JSON.parse(localStorage.getItem(key)||'null');if(!draft){feedback.textContent='No saved request draft.';return;}if(draft.request_id!==(existing?.id||'')){feedback.textContent='Open the original request to restore its draft.';return;}if(!existing){paperSelect.value=draft.paper;[...irpSelect.options].forEach(o=>o.selected=draft.irps.includes(o.value));}message.value=draft.message;state.value=draft.status;invalidate();feedback.textContent='Draft restored. Review it before submitting.';}catch{feedback.textContent='This browser could not restore the draft.';}});
})();
