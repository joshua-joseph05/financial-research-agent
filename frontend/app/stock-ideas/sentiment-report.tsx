'use client';
import {useId} from 'react';
export type SentimentClaim={text:string;argument_ids:string[]};
type Argument={id:string;kind:string;stance:string;point:string;attribution:string;quote:string;source:{url:string;title:string;published:string;publisher:string;author?:string}};
export type SentimentReport={ticker:string;status:string;objective:string;overall_sentiment:string;synthesis?:{summary:SentimentClaim;bullish_arguments:SentimentClaim[];bearish_arguments:SentimentClaim[];important_developments:SentimentClaim[];disagreements:SentimentClaim[];verification_tasks:SentimentClaim[]}|null;arguments:Argument[];coverage?:{window_days:number;candidates_discovered:number;articles_attempted:number;articles_read:number;articles_used:number;publishers_used:string[];duplicate_articles:number;failed_reads:number};limitations:string[]};
const labels:Record<string,string>={bullish:'Positive arguments in the sample',bearish:'Negative arguments in the sample',mixed:'Mixed investment arguments',neutral:'Neutral commentary',insufficient_evidence:'Not enough independent commentary'};
const kinds:Record<string,string>={reported_fact:'Reported fact · not independently verified',management_claim:'Management claim',analyst_opinion:'Attributed analyst opinion',author_opinion:'Author opinion',forecast:'Forecast · uncertain',speculation:'Speculation'};
export function SentimentCard({result}:{result:SentimentReport}){
 const prefix=useId().replaceAll(':','');
 const argumentLink=(id:string)=>`${prefix}-${result.ticker}-${id.replaceAll(':','-')}`;
 const claim=(value:SentimentClaim,key:number)=><div className="claim" key={key}><p>{value.text}</p><small>{value.argument_ids.map((id,i)=>{const evidence=result.arguments.find(a=>a.id===id);return evidence?<a key={id} href={`#${argumentLink(id)}`} onClick={()=>document.getElementById(argumentLink(id))?.closest('details')?.setAttribute('open','')}>{i>0?' · ':''}{evidence.source.publisher}</a>:null;})}</small></div>;
 const sections=result.synthesis?[
  ['The bullish case',result.synthesis.bullish_arguments],['The bearish case',result.synthesis.bearish_arguments],['Important reported developments',result.synthesis.important_developments],['Where the sources disagree',result.synthesis.disagreements],['What to check against the financials',result.synthesis.verification_tasks],
 ] as const:[];
 return <section className="panel sentiment-report" aria-label={`${result.ticker} sentiment research`}>
  <p className="eyebrow">CURRENT INVESTMENT DEBATE</p><h3>{result.ticker}: {labels[result.overall_sentiment]||'Commentary research'}</h3>
  <p className="hint">Sentiment in the reviewed article sample—not a market-wide survey or a buy signal.</p>
  {result.synthesis?claim(result.synthesis.summary,0):<p>No sufficiently supported synthesis was available. Missing commentary does not indicate positive or negative sentiment.</p>}
  {result.coverage&&<p className="hint">{result.coverage.articles_used} articles used · {result.coverage.publishers_used.length} attributed publishers · last {result.coverage.window_days} days</p>}
  <div className="reason-grid">{sections.map(([title,items])=>items.length>0&&<section key={title}><h4>{title}</h4>{items.map(claim)}</section>)}</div>
  {result.arguments.length>0&&<details><summary>Source evidence and information types ({result.arguments.length})</summary>{result.arguments.map(argument=><div className="evidence" key={argument.id} id={argumentLink(argument.id)}><strong>{kinds[argument.kind]||argument.kind}</strong><p>{argument.point}</p><blockquote>{argument.quote}</blockquote><p>{argument.attribution&&`${argument.attribution} · `}{argument.source.publisher} · {argument.source.published}{argument.source.author?` · Author: ${argument.source.author}`:''}</p>{/^https?:\/\//.test(argument.source.url)&&<a href={argument.source.url} target="_blank" rel="noreferrer">{argument.source.title}</a>}</div>)}</details>}
  <details><summary>Coverage and uncertainty</summary>{result.coverage&&<p>{result.coverage.candidates_discovered} candidates discovered; {result.coverage.articles_attempted} article reads attempted; {result.coverage.failed_reads} unavailable; {result.coverage.duplicate_articles} duplicates excluded.</p>}{result.limitations.map((text,i)=><p className="hint" key={i}>{text}</p>)}</details>
 </section>;
}
