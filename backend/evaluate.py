"""Opt-in local-model smoke evaluation. Prints results; never writes research state."""
import argparse
import json
import time

from app.agent.graph import Limits, run_research
from app.providers.llm import OllamaModel

CASES = {
    'risk': 'What are the biggest risks to NVIDIA growth?',
    'margin': 'Why have Microsoft operating margins changed?',
    'compare': 'Compare NVIDIA and AMD and identify the most important differences.',
    'overview': "I'm interested in NVIDIA because of AI. What should I know?",
    'overlooked': 'What might I be overlooking about Apple?',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=None)
    parser.add_argument('--case', choices=['all', *CASES], default='risk')
    parser.add_argument('--seconds', type=float, default=480)
    args = parser.parse_args()
    model = OllamaModel(args.model)
    for name, question in CASES.items():
        if args.case not in ('all', name):
            continue
        started = time.monotonic()
        state = run_research(question, model, Limits(seconds=args.seconds,
            finalization_reserve=min(90, args.seconds / 3)))
        report = state['report']
        print(json.dumps({'case': name, 'model': model.model,
            'elapsed_seconds': round(time.monotonic()-started, 1),
            'complete': report['complete'], 'stop_reason': report['stop_reason'],
            'findings': len(report['findings']), 'tool_calls': [c['name'] for c in state['tool_calls']],
            'duplicate_calls_blocked': state['duplicate_count'], 'errors': state['errors']}), flush=True)


if __name__ == '__main__':
    main()
