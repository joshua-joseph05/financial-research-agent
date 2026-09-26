"""Small citation-bundle semantic gate, separate from saved answer grading."""
import argparse
from pathlib import Path
from .citations import BundleJudge, Bundles, RULES, validate
from app.evaluation.v2.transport import judge_call
from app.evaluation.v2.rejudge import write


def run(transport, output):
    records=[{'id':'prior','text':'Acme revenue was 100 USD in 2024.'},
             {'id':'current','text':'Acme revenue was 150 USD in 2025.'}]
    cases=[('joint_support', 'Acme revenue increased from 100 USD in 2024 to 150 USD in 2025.',records,True),
           ('missing_half','Acme revenue increased from 100 USD in 2024 to 150 USD in 2025.',records[:1],False),
           ('unsupported_cause','Acme revenue increased because it acquired Rival.',records,False),
           ('historical_not_forecast','Acme projects revenue of 150 USD in 2025.',records,False)]
    results=[]
    for name,text,evidence,expected in cases:
        context={'claims':[{'id':'c','text':text,'cited_evidence':evidence}],'instruction':RULES}
        job=judge_call(transport,context,Bundles,validate)
        actual=job['judgment']['claims'][0]['supports_all'] if job['status']=='ok' else None
        results.append(dict(name=name,expected=expected,actual=actual,passed=actual is expected,job=job))
        write(output,dict(results=results,passed=sum(r['passed'] for r in results),total=len(cases)))
        print(name,actual,flush=True)
    return all(r['passed'] for r in results)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Preserve prior calibration; choose a new output file.')
    if not run(BundleJudge(),args.output):raise SystemExit(1)


if __name__=='__main__':main()
