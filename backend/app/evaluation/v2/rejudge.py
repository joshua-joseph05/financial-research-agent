"""Rejudge saved pairs only. python -m app.evaluation.v2.rejudge --help"""
import argparse,hashlib,json,math,random,shutil,fcntl
from pathlib import Path
from datetime import datetime,timezone
from . import VERSION
from .engine import evaluate
from .transport import OllamaJudge
from .report import summary,render
from app.evaluation.checks import answer_claims

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,data):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n');temp.replace(path)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',default='gemma4:e4b');parser.add_argument('--max-requests',type=int,default=0)
    parser.add_argument('--resume',action='store_true');parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();files=sorted(args.source.glob('*-comparison.json'))
    if not files:parser.error('No saved comparison pairs found')
    if args.output.resolve()==args.source.resolve():parser.error('Original artifacts must not be overwritten')
    originals=[json.loads(p.read_text()) for p in files]
    bound=sum(2*(1+2*math.ceil(len(answer_claims(p[s]))/2)) for p in originals for s in ('agent','baseline'))
    print(f'{len(files)} saved pairs; 0 new answers; at most {bound} local judge requests including retries.',flush=True)
    if args.dry_run:return
    if args.max_requests<bound:parser.error('Explicit --max-requests must cover the printed bound')
    if args.output.exists() and not args.resume:parser.error('Choose a new output directory or --resume')
    args.output.mkdir(parents=True,exist_ok=args.resume)
    with (args.output/'.run.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:parser.error('Already running')
        hashes={p.name:digest(p) for p in files+[args.source/'manifest.json',args.source/'comparison.json',args.source/'comparison.md']}
        code={p.name:digest(p) for p in Path(__file__).parent.glob('*.py')}
        manifest_path=args.output/'manifest.json'
        settings={'version':VERSION,'model':args.model,'source':str(args.source.resolve()),'source_hashes':hashes,'evaluator_code':code,'max_attempts':2}
        if manifest_path.exists():
            manifest=json.loads(manifest_path.read_text())
            if manifest['settings']!=settings:parser.error('Source/model/evaluator changed: use a new output directory')
        else:
            manifest={'settings':settings,'created_at':datetime.now(timezone.utc).isoformat(),'request_upper_bound':bound,'planned_pairs':len(files),'state':'running'}
            archive=args.output/'original';archive.mkdir()
            for name in hashes:shutil.copyfile(args.source/name,archive/name)
            rubric=args.output/'evaluator_snapshot';rubric.mkdir()
            for path in Path(__file__).parent.glob('*.py'):shutil.copyfile(path,rubric/path.name)
            for name in ('judge.py','checks.py','baseline.py','baseline_report.py'):
                shutil.copyfile(Path(__file__).parents[1]/name,rubric/('v1_'+name))
            write(manifest_path,manifest)
        old=json.loads((args.source/'comparison.json').read_text())
        original_manifest=json.loads((args.source/'manifest.json').read_text())
        cases={c['id']:c for c in original_manifest['source_manifest']['cases']}
        completed=[];transport=OllamaJudge(args.model)
        for index,pair in enumerate(originals):
            path=args.output/(pair['id']+'-v2.json')
            result=json.loads(path.read_text()) if path.exists() else {'original':pair,'corrected':{}}
            order=['agent','baseline'];random.Random(pair['id']).shuffle(order)
            for system in order:
                cached=result['corrected'].get(system)
                if cached and 'metrics' in cached:continue
                print(f'[{index+1}/{len(files)}] {pair["case_id"]}: rejudging {system}',flush=True)
                def save(value):
                    result['corrected'][system]=value;write(path,result)
                evaluate(pair,system,cases[pair['case_id']],transport,save,cached)
            completed.append(result)
            report=summary(completed,old,len(files));write(args.output/'comparison-v2.json',report)
            (args.output/'comparison-v2.md').write_text(render(report))
            print(f'[{index+1}/{len(files)}] Saved corrected pair.',flush=True)
        if any(digest(args.source/name)!=value for name,value in hashes.items()):raise ValueError('Source artifacts changed during rejudging')
        manifest.update(state='complete',finished_at=datetime.now(timezone.utc).isoformat());write(manifest_path,manifest)
        print('Finished: '+str(args.output/'comparison-v2.md'),flush=True)
if __name__=='__main__':main()
