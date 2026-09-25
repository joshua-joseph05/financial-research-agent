'use client';
type Source = {id: string; title: string; uri: string};
type Finding = {id: string; text: string; evidence_ids: string[]; scope?: string; segment?: string; fiscal_years: number[]};
type Evidence = {id: string; source_id: string; text?: string; value?: string | number; unit?: string; input_ids?: string[]};
type Guide = {overview: string; status: string; explanations: {title: string; explanation: string; why_it_matters: string; evidence_ids: string[]; figures: {period: string; value: string}[]}[]; glossary: {term: string; definition: string}[]; next_steps: string[]};
export type ResearchReport = {telemetry?:{model_calls:number;request_budget_used:number;request_budget:number;elapsed_seconds:number};beginner_guide?: Guide | null; question: string; answer: string; complete: boolean; synthetic: boolean; as_of: string; stop_reason: string; findings: Finding[]; sources: Source[]; evidence: Evidence[]; limitations: string[]; follow_up_questions: string[]};

function safeLink(url:string){return /^https?:\/\//i.test(url)?url:undefined;}
export function ResearchResults({report,busy,onFollowUp}:{report:ResearchReport;busy:boolean;onFollowUp:(question:string)=>void}){
 const setQuestion=onFollowUp;
  function citationDetails(ids: string[]) {
    if (!report) return null;
    const collected = new Set<string>();
    function include(id: string) {
      if (collected.has(id)) return;
      collected.add(id);
      report?.evidence.find(e => e.id === id)?.input_ids?.forEach(include);
    }
    ids.forEach(include);
    return <details className="citations"><summary>See the evidence and sources</summary>{[...collected].map(id => {
      const evidence = report.evidence.find(item => item.id === id);
      const source = report.sources.find(item => item.id === evidence?.source_id);
      return <div key={id} className="evidence"><p>{evidence?.text || 'Evidence unavailable'}</p>{source && (safeLink(source.uri) ? <a href={source.uri} target="_blank" rel="noreferrer">{source.title}</a> : <span>{source.title}</span>)}</div>;
    })}</details>;
  }
 return <article className="report research-report" aria-label="Research report"><div className="report-heading"><p className="eyebrow">YOUR RESEARCH, EXPLAINED</p><span className={report.complete ? 'badge' : 'badge partial'}>{report.complete ? 'Evidence reviewed' : report.findings.length ? 'Some questions remain' : 'Research could not finish'}</span></div><h2>{report.question}</h2><p className="hint">{report.synthetic ? 'FICTIONAL DEMO DATA' : 'Public-source research'} · Researched {new Date(report.as_of).toLocaleString()}</p>
      {report.synthetic&&<p className="demo-notice">Fictional demo · These figures illustrate the workflow and should not inform investment decisions.</p>}
      <div className="research-summary"><div><strong>{report.findings.length}</strong><span>Reviewed findings</span></div><div><strong>{report.sources.length}</strong><span>Sources collected</span></div><div><strong>{report.follow_up_questions.length}</strong><span>Open questions</span></div></div>
      {report.beginner_guide ? <>
        <section className="takeaway research-takeaway"><p className="eyebrow">START HERE</p><h3>The takeaway</h3><p>{report.beginner_guide.overview || 'We could not establish a supported answer yet.'}</p><p className="reading-status">{report.beginner_guide.status}</p></section>
        {report.beginner_guide.explanations.length>0&&<div className="research-section-heading"><p className="eyebrow">UNDERSTAND THE EVIDENCE</p><h3>What the research tells us</h3><p>Key findings, explained in plain English.</p></div>}<div className="research-findings">
        {report.beginner_guide.explanations.map((item,i) => <section className="explanation research-finding" key={i}><span className="finding-number">FINDING {String(i+1).padStart(2,'0')}</span><h4>{item.title}</h4><p>{item.explanation}</p><div className="why-matters"><strong>Why it matters</strong><p>{item.why_it_matters}</p></div>{item.figures.length > 1 && <div className="table-scroll"><table><caption>Operating margin by financial year</caption><thead><tr><th scope="col">Year ending</th><th scope="col">Operating margin</th></tr></thead><tbody>{item.figures.map((row,j) => <tr key={j}><td>{row.period}</td><td>{row.value}</td></tr>)}</tbody></table></div>}{citationDetails(item.evidence_ids)}</section>)}</div>
        {report.beginner_guide.glossary.length > 0 && <section className="glossary research-glossary"><h3>Financial terms in plain English</h3><dl>{report.beginner_guide.glossary.map(item => <div key={item.term}><dt>{item.term}</dt><dd>{item.definition}</dd></div>)}</dl></section>}
        {report.beginner_guide.next_steps.length>0&&<section className="research-next"><p className="eyebrow">KEEP EXPLORING</p><h3>What to look into next</h3><ol>{report.beginner_guide.next_steps.map(item => <li key={item}>{item}</li>)}</ol></section>}
      </> : <div className="answer">{report.answer}</div>}
      {report.follow_up_questions.length > 0 && <section className="open-questions"><p className="eyebrow">STILL TO INVESTIGATE</p><h3>Questions the research leaves open</h3><p className="hint">Choose a question to put it in the research box.</p><div>{report.follow_up_questions.map((item,i) => <button type="button" disabled={busy} key={i} onClick={()=>{setQuestion(item);document.getElementById('question')?.focus();document.getElementById('question')?.scrollIntoView({behavior:'smooth',block:'center'});}}>{item}<span aria-hidden="true">↗</span></button>)}</div></section>}
      {report.limitations.length>0&&<section className="research-limits"><h3>What this report cannot establish</h3><ul>{report.limitations.map((item,i)=><li key={i}>{item}</li>)}</ul></section>}
      <details className="audit"><summary>Explore detailed findings</summary><h3>Verified findings</h3>{report.findings.map(finding => <section className="finding" key={finding.id}><p>{finding.text}</p><small>{[finding.scope, finding.segment, finding.fiscal_years?.join(' / ')].filter(Boolean).join(' · ')}</small>{citationDetails(finding.evidence_ids)}</section>)}</details>
      <details className="audit"><summary>Source library ({report.sources.length})</summary><ul>{report.sources.map(source => <li key={source.id}>{safeLink(source.uri) ? <a href={source.uri} target="_blank" rel="noreferrer">{source.title}</a> : source.title}</li>)}</ul></details>
      {report.telemetry&&<details className="audit"><summary>Run metrics</summary><p>{report.telemetry.model_calls} model calls · {report.telemetry.request_budget_used}/{report.telemetry.request_budget} request budget · {Math.round(report.telemetry.elapsed_seconds)} seconds</p></details>}
    </article>;
}
