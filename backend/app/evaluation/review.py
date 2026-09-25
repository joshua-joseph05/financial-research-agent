"""Import manual reviews or regenerate aggregate summaries without model requests."""
import argparse,json
from pathlib import Path
from app.evaluation.benchmark import save_summary
from app.evaluation.benchmark_data import Case
from app.evaluation.compare import write_json
from app.evaluation.judge import judge_packet,assessment_metrics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--import-manual',action='store_true')
    args=parser.parse_args()
    manifest=json.loads((args.directory/'manifest.json').read_text())
    cases={c['id']:Case.model_validate(c) for c in manifest['cases']}
    index=json.loads((args.directory/'index.json').read_text());items=[]
    for row in index:
        path=args.directory/(row['label']+'.json');run=json.loads(path.read_text())
        if args.import_manual:
            manual=json.loads((args.directory/(row['label']+'.review.json')).read_text())
            if manual.get('task') is not None or manual.get('claims') or manual.get('sentiment') is not None:
                if manual.get('method')!='manual' or not manual.get('reviewer','').strip():raise ValueError('Manual assessment requires method=manual and a reviewer')
                # Validate against original run evidence, not an edited review packet.
                manual['metrics']=assessment_metrics(judge_packet(cases[run['case_id']],run),manual)
                run['manual']={k:v for k,v in manual.items() if k not in ('packet','instructions')}
                write_json(path,run)
        items.append(run)
    save_summary(args.directory,items,manifest['planned_runs'])
    print('Saved summary.json and summary.md. No model requests made.')

if __name__=='__main__':main()
