import argparse
import json
import os
import sys

from app.agent.graph import Limits, run_research
from app.providers.demo import DemoModel
from app.providers.openrouter import create_model
from app.providers.sec import SECClient
from app.tools.registry import ToolRegistry


def main():
    parser = argparse.ArgumentParser(description="Local financial research with SEC data or synthetic fixtures")
    parser.add_argument("question")
    parser.add_argument("--mode", choices=["local", "demo"], default="local")
    parser.add_argument("--data", choices=["sec", "fixture"], help="Defaults to SEC for local mode, fixtures for demo")
    parser.add_argument("--model", help="Model name for the configured provider")
    parser.add_argument("--seconds", type=float, default=480, help="Run time budget, including finalization")
    parser.add_argument("--max-tools", type=int, default=10)
    parser.add_argument("--trace", action="store_true", help="Print plan and tool trace to stderr")
    args = parser.parse_args()
    sec = None
    try:
        data = args.data or ("fixture" if args.mode == "demo" else "sec")
        if args.mode == "demo" and data != "fixture":
            raise ValueError("Scripted demo supports fixture data only")
        if data == "sec":
            sec = SECClient(os.getenv("SEC_USER_AGENT", ""))
        model = DemoModel() if args.mode == "demo" else create_model(args.model)
        def progress(event):
            if args.trace:
                print(f"[{event['phase']}] {event['event']}", file=sys.stderr, flush=True)
        state = run_research(args.question, model, Limits(max_tool_calls=args.max_tools,
            seconds=args.seconds, finalization_reserve=min(90, args.seconds / 3)), on_event=progress, registry=ToolRegistry(sec=sec))
    except ValueError as error:
        parser.error(str(error))
    finally:
        if sec:
            sec.close()
    if args.mode == "demo":
        print("SCRIPTED DEMO — supports NVIDIA risks or Microsoft margins only.", file=sys.stderr)
    if args.trace:
        print(json.dumps({"plan": state["plan"], "events": state["events"],
            "tools": [{"name": c["name"], "arguments": c["arguments"], "status": c["result"]["status"]}
                      for c in state["tool_calls"]], "iterations": state["iteration_count"]}, indent=2), file=sys.stderr)
    print(json.dumps(state["report"], indent=2))


if __name__ == "__main__":
    main()
