'use client';
import {useState} from 'react';
import {ResearchResults,type ResearchReport} from './research-results';
import {InvestmentResults,type InvestmentReport} from './investment-results';
type Result={workflow:'research';report:ResearchReport;routing:{reason:string}}|{workflow:'investment'|'education';report:InvestmentReport;routing:{reason:string}};
type Progress={phase:string;event:string;result?:{message?:string}};
const api=process.env.NEXT_PUBLIC_API_URL||'http://127.0.0.1:8000';
const examples=[
 {label:'Understand a company',question:'What might I be overlooking about Apple?',symbol:'01'},
 {label:'Explore investments',question:'What stocks could I research for long-term investing?',symbol:'02'},
 {label:'Compare the possibilities',question:'Compare Microsoft and NVIDIA as long-term investments.',symbol:'03'},
 {label:'Learn the basics',question:'What is diversification?',symbol:'04'},
];
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
 return <main className="research-page ideas-page assistant-home">
 <header className="home-header"><a className="home-brand" href="/" aria-label="Fieldnotes home"><span className="brand-mark" aria-hidden="true">f.</span><span>fieldnotes<span className="brand-descriptor">FINANCIAL RESEARCH</span></span></a><a className="header-link" href="#how-it-works">How it works <span aria-hidden="true">↗</span></a></header>
 <section className="home-hero"><p className="home-eyebrow"><span aria-hidden="true"/>YOUR CURIOSITY. A CLEARER PICTURE.</p><h1>Good decisions start<br/>with <em>better questions.</em></h1><p>Make sense of companies, explore investments, and understand<br className="desktop-break"/> the evidence behind the story. Start with what’s on your mind.</p></section>
 <form className="question-composer" onSubmit={submit} aria-busy={busy}>
 <div className="composer-heading"><label htmlFor="question">What would you like to explore?</label><span className="composer-tag">ASK IN YOUR OWN WORDS</span></div>
 <textarea id="question" value={question} onChange={e=>setQuestion(e.target.value)} disabled={busy} required minLength={3} maxLength={2000} aria-describedby="question-help" placeholder="I'm interested in NVIDIA because of AI. What should I know?"/>
 <div className="composer-bottom"><p id="question-help">A company, a comparison, or a question about investing.<span>{question.length > 1700 ? `${question.length} / 2,000 characters` : 'Add your goals or time horizon for more context.'}</span></p><button className="primary research-button" disabled={busy||question.trim().length<3}>{busy?'Investigating…':'Start researching'}<span aria-hidden="true">{busy?'◌':'↗'}</span></button></div>
 </form>
 {!busy&&!result&&<section className="starter-section" aria-labelledby="starter-heading"><div className="section-caption"><h2 id="starter-heading">A few places to start</h2><span>FOLLOW YOUR CURIOSITY</span></div><div className="starter-grid">{examples.map(example=><button type="button" className="starter-card" key={example.symbol} onClick={()=>{setQuestion(example.question);document.getElementById('question')?.focus();}}><span className="starter-label"><span>{example.symbol}</span>{example.label}</span><span className="starter-question">{example.question}</span><span className="starter-arrow" aria-hidden="true">↗</span></button>)}</div></section>}
 <p className="run-note">Research takes a few minutes. The assistant follows the evidence and investigates recent commentary when relevant.</p>
 {error&&<p role="alert" className="error">{error}</p>}
 {(busy||events.length>0)&&<section className="panel research-progress"><h2>Research progress</h2><p role="status">{busy?(events.at(-1)?.result?.message||`Working: ${events.at(-1)?.phase||'starting'}`):'Run finished'}</p><details><summary>Research activity</summary><ol>{events.map((event,i)=><li key={i}>{event.result?.message||event.phase}</li>)}</ol></details></section>}
 {result&&<><p className="hint">{result.routing.reason}</p>{result.workflow==='research'?<ResearchResults report={result.report} busy={busy} onFollowUp={setQuestion}/>:<InvestmentResults report={result.report}/>}</>}
 <section className="how-section" id="how-it-works" aria-labelledby="how-heading"><div className="how-intro"><p className="eyebrow">FROM QUESTION TO CLARITY</p><h2 id="how-heading">Research you can<br/>look into.</h2></div><div className="how-step"><span>01 / INVESTIGATE</span><h3>Follow the question</h3><p>The assistant chooses tools to explore financials, filings, and relevant public commentary.</p></div><div className="how-step"><span>02 / CHECK</span><h3>Examine the evidence</h3><p>Calculations run in Python. Claims are checked against sources, with gaps called out.</p></div><div className="how-step"><span>03 / UNDERSTAND</span><h3>See the reasoning</h3><p>Get a plain-language report with source links, risks, and questions worth exploring next.</p></div></section><footer className="home-footer"><span>fieldnotes <span aria-hidden="true">/</span> Built for curious investors.</span><span>Research for your own decisions. No trade execution.</span></footer></main>;
}
