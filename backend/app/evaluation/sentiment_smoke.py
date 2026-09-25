"""Opt-in live-source/local-or-hosted LLM smoke test; writes an auditable handoff."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from app.ideas.sentiment import consult, ConsultArgs, handoff
from app.ideas.graph import SYSTEM
from app.ideas.telemetry import MeteredModel
from app.providers.openrouter import create_model
from app.providers.sec import SECClient
from app.tools.registry import ToolRegistry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker',required=True)
    parser.add_argument('--objective',default='Investigate important current bullish and bearish investment arguments, distinguish reported facts from opinions and forecasts, and identify the financial evidence to check.')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--budget',type=int,default=20)
    args=parser.parse_args()
    if not 4<=args.budget<=36:parser.error('budget must be 4–36')
    if args.output.exists():parser.error('Use a new output directory to preserve prior runs')
    args.output.mkdir(parents=True)
    base=create_model(system_prompt=SYSTEM);model=MeteredModel(base,args.budget)
    sec=SECClient(os.getenv('SEC_USER_AGENT',''))
    try:
        result=consult(ConsultArgs(ticker=args.ticker.upper(),objective=args.objective),model,ToolRegistry(sec=sec),time.monotonic()+600,emit=lambda e:print(e['result']['message'],flush=True))
    finally:sec.close()
    result['telemetry']=model.report()
    result['run']={'as_of':datetime.now(timezone.utc).isoformat(),'provider':os.getenv('LLM_PROVIDER','ollama'),'model':base.model}
    (args.output/'report.json').write_text(json.dumps(result,indent=2))
    (args.output/'lead-handoff.json').write_text(json.dumps(handoff(result),indent=2))
    print(json.dumps({'status':result['status'],'overall_sentiment':result['overall_sentiment'],'coverage':result['coverage'],'model_calls':model.report()['model_calls']},indent=2))
    print('This is a live smoke check, not proof of representative coverage or investment accuracy.')


if __name__=='__main__':main()
