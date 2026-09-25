'use client';
import {useState} from 'react';
import {ResearchResults,type ResearchReport} from './research-results';
import {InvestmentResults,type InvestmentReport} from './investment-results';
type Result={workflow:'research';report:ResearchReport;routing:{reason:string}}|{workflow:'investment'|'education';report:InvestmentReport;routing:{reason:string}};
type Progress={phase:string;event:string;result?:{message?:string}};
const api=process.env.NEXT_PUBLIC_API_URL||'http://127.0.0.1:8000';
const examples=['Why have Microsoft operating margins changed?','What might I be overlooking about Apple?','What stocks could I research for long-term investing?','Compare Microsoft and NVIDIA as long-term investments.','What is diversification?'];
export default function Home(){
 const [question,setQuestion]=useState('');
 const [busy,setBusy]=useState(false);const [events,setEvents]=useState<Progress[]>([]);const [result,setResult]=useState<Result|null>(null);const [error,setError]=useState('');
 async function submit(e:React.FormEvent){
  e.preventDefault();setBusy(true);setError('');setResult(null);setEvents([]);let received=false;
  try{
   const response=await fetch(`${api}/assistant`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});
   if(!response.ok){const body=await response.json();throw new Error(typeof body.detail==='string'?body.detail:'Check your question and try again.');}
   if(!response.body)throw new Error('The server did not return a stream.');
   const reader=response.body.getReader();const decoder=new TextDecoder();let pending='';
   function consume(line:string){if(!line.trim())return;const event=JSON.parse(line);if(event.type==='progress')setEvents(previous=>[...previous,event]);if(event.type==='report'){setResult(event.report);received=true;}if(event.type==='error')throw new Error(event.message);}
   try{while(true){const {value,done}=await reader.read();pending+=decoder.decode(value,{stream:!done});const lines=pending.split('\n');pending=lines.pop()||'';lines.forEach(consume);if(done){consume(pending);break;}}}finally{reader.releaseLock();}
   if(!received)throw new Error('The connection ended before a report arrived. The server may still be finishing.');
  }catch(err){setError(err instanceof Error?err.message:'Unable to finish research.');}finally{setBusy(false);}
 }
 return <main className="research-page ideas-page"><header><span className="brand">FIELDNOTES / FINANCIAL ASSISTANT</span></header>
 <section className="intro"><p className="eyebrow">ONE QUESTION. FOLLOW THE EVIDENCE.</p><h1>Understand companies.<br/>Explore investment decisions.</h1><p>Ask about a business, its financials, potential investments, or investing basics. The assistant chooses the research approach and explains what the evidence supports.</p></section>
 <form className="panel" onSubmit={submit}><label htmlFor="question">What would you like to understand?</label><textarea id="question" value={question} onChange={e=>setQuestion(e.target.value)} disabled={busy} required minLength={3} maxLength={2000} placeholder="Ask a company question, compare investments, or explore an investing concept…"/>
 <div className="question-examples">{examples.map(text=><button type="button" key={text} disabled={busy} onClick={()=>setQuestion(text)}>{text}</button>)}</div>
 <p className="hint">The assistant can consult its sentiment agent when current commentary is relevant. Include your goals or time horizon in your question when useful.</p>
 <button className="primary" disabled={busy||question.trim().length<3} style={{marginTop:24}}>{busy?'Investigating…':'Explore my question →'}</button><p className="hint">Live research can take several minutes. Sentiment investigations may add several minutes.</p></form>
 {error&&<p role="alert" className="error">{error}</p>}
 {(busy||events.length>0)&&<section className="panel research-progress"><h2>Research progress</h2><p role="status">{busy?(events.at(-1)?.result?.message||`Working: ${events.at(-1)?.phase||'starting'}`):'Run finished'}</p><details><summary>Research activity</summary><ol>{events.map((event,i)=><li key={i}>{event.result?.message||event.phase}</li>)}</ol></details></section>}
 {result&&<><p className="hint">{result.routing.reason}</p>{result.workflow==='research'?<ResearchResults report={result.report} busy={busy} onFollowUp={setQuestion}/>:<InvestmentResults report={result.report}/>}</>}
 <footer>Research and educational support for your own decisions. No trade execution or saved reports.</footer></main>;
}
