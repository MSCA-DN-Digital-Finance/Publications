'use strict';
(() => {
  const data=JSON.parse(document.getElementById('research-data').textContent);
  const split=value=>(value||'').split(';').map(s=>s.trim()).filter(Boolean);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const normalizeDOI=value=>value.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'').toLowerCase();
  const validURL=value=>{try{return ['http:','https:'].includes(new URL(value).protocol)&&!(/\s/.test(value));}catch{return false;}};
  const all=[...data.publications.map(r=>({...r,kind:'publication'})),...data.working_papers.map(r=>({...r,kind:'working-paper'}))];
  const people=new Map((data.people||[]).map(p=>[p.number,p]));
  const irpLabel=number=>{const p=people.get(number);return p?'IRP '+number+' · '+(p.candidate?.name||p.short_title):'IRP '+number;};
  const results=document.getElementById('records');
  if(results){
    const kind=document.body.dataset.collection;
    const rows=all.filter(r=>r.kind===kind);
    const controls=['subject','irp','year',...(kind==='publication'?['type','access']:['collaboration','status'])];
    const params=new URLSearchParams(location.search);
    const fieldMap={subject:'subjects',irp:'irp_numbers',year:'year',type:'type',access:'access',collaboration:'open_to_collaborate',status:'status'};
    const search=document.getElementById('search');search.value=params.get('q')||'';
    const sort=document.getElementById('sort');if(['year','title','updated'].includes(params.get('sort')))sort.value=params.get('sort');
    for(const [control,key] of [['subject','subjects'],['irp','irp_numbers'],['year','year']]){
      const select=document.getElementById(control+'-filter');
      const values=[...new Set(rows.flatMap(r=>split(r[key])))].sort((a,b)=>control==='year'?b.localeCompare(a):a.localeCompare(b,undefined,{numeric:true}));
      values.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=control==='irp'?irpLabel(value):value;select.append(option);});
    }
    controls.forEach(name=>{const control=document.getElementById(name+'-filter');if(params.has(name))control.value=params.get(name);control.addEventListener('change',render);});
    const counts=new Map();rows.forEach(r=>new Set(split(r.subjects)).forEach(s=>counts.set(s,(counts.get(s)||0)+1)));
    const cloud=document.getElementById('subject-cloud');
    const max=Math.max(1,...counts.values());
    cloud.innerHTML=rows.length?'<button class="subject-chip subject-all" data-subject="" aria-pressed="true">All subjects</button>'+[...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).map(([s,n])=>`<button class="subject-chip" data-subject="${escape(s)}" aria-pressed="false" style="--subject-size:${14+10*Math.sqrt(n/max)}px">${escape(s)} <span class="subject-count">${n}</span></button>`).join(''):'<span class="muted">Subjects will appear when working papers are added.</span>';
    const cards=new Map([...results.querySelectorAll('[data-record-id]')].map(card=>[card.dataset.recordId,card]));
    function render(){
      const filter=Object.fromEntries(controls.map(name=>[name,document.getElementById(name+'-filter').value]));
      const words=search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      const found=rows.filter(r=>words.every(word=>Object.values(r).join(' ').toLowerCase().includes(word))&&controls.every(name=>!filter[name]||split(r[fieldMap[name]]).includes(filter[name]))).sort((a,b)=>sort.value==='title'?a.title.localeCompare(b.title):sort.value==='updated'?(b.last_updated||'').localeCompare(a.last_updated||'')||a.title.localeCompare(b.title):(b.year||'').localeCompare(a.year||'')||a.title.localeCompare(b.title));
      cards.forEach(card=>card.hidden=true);found.forEach(r=>{const card=cards.get(r.id);card.hidden=false;results.append(card);});
      document.getElementById('result-count').textContent=found.length+' '+(kind==='publication'?(found.length===1?'publication / preprint':'publications / preprints'):(found.length===1?'working paper':'working papers'));
      const empty=document.getElementById('empty');empty.hidden=found.length>0;
      empty.querySelector('h2').textContent=!rows.length&&kind==='working-paper'?'No working papers yet':'No matching records';
      document.getElementById('empty-reset').hidden=!rows.length;
      document.getElementById('empty-message').textContent=!rows.length?(kind==='working-paper'?'Add a working paper to share your topic or invite collaborators.':'Add the first publication or preprint.'):'Try another search or clear your filters.';
      cloud.querySelectorAll('[data-subject]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.subject===filter.subject)));
      const query=new URLSearchParams();if(search.value)query.set('q',search.value);controls.forEach(name=>{if(filter[name])query.set(name,filter[name]);});if(sort.value!=='year')query.set('sort',sort.value);
      history.replaceState(null,'',location.pathname+(query.size?'?'+query.toString():'')+location.hash);
    }
    function reset(){search.value='';sort.value='year';controls.forEach(name=>document.getElementById(name+'-filter').value='');render();}
    search.addEventListener('input',render);sort.addEventListener('change',render);
    document.getElementById('reset').addEventListener('click',reset);document.getElementById('empty-reset').addEventListener('click',reset);
    document.getElementById('toggle-filters').addEventListener('click',event=>event.currentTarget.setAttribute('aria-expanded',String(document.getElementById('research-filters').classList.toggle('mobile-open'))));
    cloud.addEventListener('click',event=>{const button=event.target.closest('[data-subject]');if(!button)return;const select=document.getElementById('subject-filter');const value=select.value===button.dataset.subject?'':button.dataset.subject;reset();select.value=value;render();document.getElementById('research-results').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'start'});});
    document.addEventListener('click',async event=>{const button=event.target.closest('[data-copy]');if(!button)return;const url=new URL(location.href);url.hash=button.dataset.copy;try{await navigator.clipboard.writeText(url.href);button.textContent='Link copied';}catch{location.hash=button.dataset.copy;button.textContent='Copy the URL from your address bar';}});
    function route(){const match=location.hash.match(/^#(publication|working-paper)\/([a-z0-9-]+)$/);if(!match||match[1]!==kind)return;const card=cards.get(match[2]);if(card){reset();card.querySelector('details').open=true;card.scrollIntoView({block:'start'});}}
    addEventListener('hashchange',route);render();route();
    // Software records are maintained independently; show current reverse links
    // without making publication builds depend on another repository being online.
    fetch('/Open_Software/data/software.json',{signal:AbortSignal.timeout(10000)}).then(async response=>{
      if(!response.ok)return;
      const software=(await response.json()).software;
      if(!Array.isArray(software))return;
      for(const row of rows){
        const related=software.filter(item=>/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(item.id)&&(
          split(item[kind==='publication'?'publication_ids':'working_paper_ids']).includes(row.id)||
          split(item.paper_urls).some(url=>url===row.link||(row.doi&&url.toLowerCase()==='https://doi.org/'+normalizeDOI(row.doi)))));
        if(!related.length)continue;
        const section=document.createElement('section'),heading=document.createElement('h3'),list=document.createElement('ul');
        heading.textContent='Related open software';section.className='related-software';section.append(heading,list);
        related.forEach(item=>{const li=document.createElement('li'),link=document.createElement('a');link.href='/Open_Software/#software/'+item.id;link.textContent=item.name;li.append(link);list.append(li);});
        cards.get(row.id).querySelector('details').append(section);
      }
    }).catch(()=>{});
  }
  const form=document.getElementById('research-form');
  if(form){
    const control=name=>form.elements.namedItem(name);
    const status=document.getElementById('form-status');
    const params=new URLSearchParams(location.search);
    if(['publication','working-paper'].includes(params.get('kind')))control('kind').value=params.get('kind');
    const existing=all.find(r=>r.kind===params.get('kind')&&r.id===params.get('id'));
    if(existing){for(const element of form.elements){if(element.name&&existing[element.name]!==undefined)element.value=existing[element.name];}control('action').value='update';}
    const irpInput=control('irp_numbers');
    const irpChoices=document.createElement('datalist');irpChoices.id='irp-choices';
    for(const p of people.values()){const option=document.createElement('option');option.value=p.number;option.label=irpLabel(p.number);irpChoices.append(option);}
    irpInput.setAttribute('list','irp-choices');form.append(irpChoices);
    function assignCandidate(){const numbers=split(irpInput.value);if(numbers.length&&numbers.every(n=>people.has(n))){control('researcher_names').value=numbers.map(n=>people.get(n).candidate?.name||'').filter(Boolean).join(';');}}
    irpInput.addEventListener('change',assignCandidate);
    if(params.get('irp')&&people.has(params.get('irp'))&&!existing){irpInput.value=params.get('irp');assignCandidate();}
    function sync(){
      const kind=control('kind').value;
      document.querySelectorAll('[data-for]').forEach(field=>{field.hidden=field.dataset.for!==kind;field.querySelectorAll('input,select,textarea').forEach(input=>input.disabled=field.hidden);});
      control('year').required=kind==='publication';control('link').required=kind==='publication';control('summary').required=kind==='working-paper';
      control('venue').required=kind==='publication'&&['journal-article','conference-paper','book-chapter'].includes(control('type').value);
      const collaborate=kind==='working-paper'&&control('open_to_collaborate').value==='yes';
      control('collaboration_needs').required=collaborate;control('contact_url').required=collaborate;
    }
    ['kind','type','open_to_collaborate'].forEach(name=>control(name).addEventListener('change',sync));sync();
    let proposal;
    form.addEventListener('input',()=>{proposal=null;document.getElementById('proposal-review').hidden=true;status.textContent='';});
    form.addEventListener('change',()=>{proposal=null;document.getElementById('proposal-review').hidden=true;});
    form.addEventListener('submit',event=>{
      event.preventDefault();const values=new FormData(form);const record={};
      for(const [key,value] of values)if(!['kind','action'].includes(key))record[key]=String(value).trim();
      const kind=control('kind').value,action=control('action').value;
      if(!record.id)record.id=(record.title||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
      if(!record.id){status.textContent='Please enter an ID using lowercase letters, numbers and hyphens.';return;}
      const match=all.find(r=>r.kind===kind&&r.id===record.id);
      if(action==='add'&&match){status.textContent='This ID exists. Choose an update or another ID.';return;}
      if(action==='update'&&!match){status.textContent='This ID does not exist. Choose a new record or check the ID.';return;}
      if(record.doi){record.doi=normalizeDOI(record.doi);if(!/^10\.\d{4,9}\/\S+$/.test(record.doi)){status.textContent='Please enter a valid DOI, or leave it blank.';return;}if(data.publications.some(r=>normalizeDOI(r.doi||'')===record.doi&&r.id!==record.id)){status.textContent='This DOI already exists. Update the existing publication.';return;}}
      for(const [key,value] of Object.entries(record))if(value&&(key==='link'||key.endsWith('_url'))&&!validURL(value)){status.textContent='Use public http:// or https:// links.';return;}
      proposal={kind,action,record};
      document.getElementById('proposal-json').textContent=JSON.stringify(proposal,null,2);
      const body='## Research proposal\n\nPlease review this record before applying the publication-approved label.\n\n```json\n'+JSON.stringify(proposal,null,2)+'\n```';
      const url=data.config.repository+'/issues/new?'+new URLSearchParams({template:'research-proposal.md',title:`[Research ${action}] ${record.title}`,body});
      const issue=document.getElementById('open-issue');issue.href=url;issue.hidden=url.length>7000;
      document.getElementById('long-proposal').hidden=url.length<=7000;document.getElementById('proposal-review').hidden=false;
      status.textContent='Proposal prepared. Nothing has been sent; review it and submit the issue on GitHub.';
      document.getElementById('proposal-review').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});
    });
    document.getElementById('download-json').addEventListener('click',()=>{if(!proposal)return;const url=URL.createObjectURL(new Blob([JSON.stringify(proposal,null,2)+'\n'],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=proposal.kind+'-'+proposal.record.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    document.getElementById('save-draft').addEventListener('click',()=>{try{const draft=Object.fromEntries([...form.elements].filter(e=>e.name).map(e=>[e.name,e.value]));localStorage.setItem('digital-research-draft',JSON.stringify(draft));status.textContent='Draft saved in this browser on this device.';}catch{status.textContent='This browser could not save the draft.';}});
    document.getElementById('restore-draft').addEventListener('click',()=>{try{const draft=JSON.parse(localStorage.getItem('digital-research-draft')||'null');if(!draft){status.textContent='No saved draft in this browser.';return;}for(const e of form.elements)if(e.name&&draft[e.name]!==undefined)e.value=draft[e.name];sync();proposal=null;document.getElementById('proposal-review').hidden=true;status.textContent='Draft restored. Review the fields before submitting.';}catch{status.textContent='This browser could not restore the draft.';}});
  }
})();
