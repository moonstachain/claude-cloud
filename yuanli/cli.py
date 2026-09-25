"""`yuanli` — the whole OS from a terminal. Every command is one kernel call."""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path
from typing import Any

from .kernel import Kernel
from .policy import Forbidden, principal
from .state import Conflict, NotFound

OUTCOMES = {"yes": 1.0, "y": 1.0, "达成": 1.0, "no": 0.0, "n": 0.0, "未达成": 0.0, "-": None, "unknown": None}
PRIORITY = "P0 P1 P2 P3".split()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="yuanli", description="原力OS — observe → propose → decide → act → settle → learn")
    root.add_argument("--home", help="data directory (default $YUANLI_HOME or ~/.yuanli)")
    sub = root.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web app and background collection")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8420)
    serve.add_argument("--collect-every", type=int, default=60, help="seconds between collection passes (0 = off)")

    sub.add_parser("today", help="what needs you today")
    collect = sub.add_parser("collect", help="pull every source, then run domain rules")
    collect.add_argument("only", nargs="*", help="domain keys or source names")

    propose = sub.add_parser("propose", help="put a decision or a forecast on the table")
    propose.add_argument("domain")
    propose.add_argument("title")
    propose.add_argument("--id")
    propose.add_argument("--why", default="")
    propose.add_argument("--recommend", default="")
    propose.add_argument("--priority", default="P2")
    propose.add_argument("--forecast", type=float)
    propose.add_argument("--due")
    propose.add_argument("--scope", default="private")

    decide = sub.add_parser("decide", help="approve, reject or defer an item")
    decide.add_argument("id")
    decide.add_argument("verdict", choices=["approve", "reject", "defer"])
    decide.add_argument("-m", "--note", default="")
    decide.add_argument("--until")
    decide.add_argument("--forecast", type=float)

    settle = sub.add_parser("settle", help="record the outcome: yes / no / 0..1 / - (unknown)")
    settle.add_argument("id")
    settle.add_argument("outcome")
    settle.add_argument("-m", "--note", default="")

    note = sub.add_parser("note", help="add progress or evidence to an item")
    note.add_argument("id")
    note.add_argument("note")

    ask = sub.add_parser("ask", help="search everything; with YUANLI_BRAIN=1 Claude answers from the hits")
    ask.add_argument("question")

    sub.add_parser("calibration", help="Brier scores: are your forecasts getting better?")
    canon = sub.add_parser("canon", help="list principles, or rule on one")
    canon.add_argument("verdict", nargs="?", choices=["admit", "reject", "retire"])
    canon.add_argument("id", nargs="?")
    canon.add_argument("-m", "--note", default="")

    export = sub.add_parser("export", help="static, action-free snapshot for an audience")
    export.add_argument("--audience", choices=["public", "team", "private"], default="public")
    export.add_argument("--out", type=Path, default=Path("dist"))

    migrate = sub.add_parser("import-osmax", help="import yuanli-os-max decision queue and calibration takes")
    migrate.add_argument("repo", type=Path)

    log = sub.add_parser("log", help="tail the ledger")
    log.add_argument("-n", type=int, default=20)

    token = sub.add_parser("token", help="mint an entry for YUANLI_TOKENS")
    token.add_argument("name")
    token.add_argument("role", choices=["principal", "agent", "viewer"])
    token.add_argument("audience", nargs="?", choices=["public", "team", "private"])
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "token":
        entry = ":".join(filter(None, [secrets.token_urlsafe(24), args.name, args.role, args.audience]))
        print(entry)
        return 0
    kernel = Kernel(args.home)
    me = principal()
    try:
        return run(kernel, me, args)
    except (NotFound, Forbidden, Conflict, ValueError) as exc:  # Invalid is a ValueError
        print(f"✗ {str(exc).strip(chr(39))}", file=sys.stderr)
        return 1


def run(kernel: Kernel, me: Any, args: argparse.Namespace) -> int:
    command = args.command
    if command == "serve":
        from .server import serve

        serve(kernel, args.host, args.port, args.collect_every)
    elif command == "today":
        print_brief(kernel.brief(me))
    elif command == "collect":
        print(kernel.collect(set(args.only) or None))
        for name, status in sorted(kernel.sources.items()):
            print(f"  {'✓' if status['ok'] else '✗'} {name:<20} {status['detail']}  ({status['ms']} ms)")
    elif command == "propose":
        data = {key: getattr(args, key) for key in ("domain", "title", "why", "recommend", "priority", "forecast", "due", "scope")}
        data["id"] = args.id or f"{args.domain}:{secrets.token_hex(4)}"
        kernel.emit(me, "item.proposed", data)
        print(f"+ {data['id']}")
    elif command == "decide":
        kernel.emit(me, "item.decided", {"id": args.id, "verdict": args.verdict, "note": args.note, "until": args.until, "forecast": args.forecast})
        print(f"✓ {args.id} → {kernel.state.items[args.id].status}")
    elif command == "settle":
        raw = args.outcome.strip().lower()
        outcome = OUTCOMES[raw] if raw in OUTCOMES else float(raw)
        kernel.emit(me, "item.settled", {"id": args.id, "outcome": outcome, "note": args.note})
        item = kernel.state.items[args.id]
        print(f"✓ {args.id} settled" + (f" · Brier {item.brier}" if item.brier is not None else ""))
    elif command == "note":
        kernel.emit(me, "item.noted", {"id": args.id, "note": args.note})
    elif command == "ask":
        result = kernel.ask(me, args.question)
        print(result["answer"])
        for n, hit in enumerate(result["citations"], 1):
            print(f"  [{n}] {hit['kind']}:{hit['id']}  {hit['title'][:60]}")
    elif command == "calibration":
        print(json.dumps(kernel.calibration(me), ensure_ascii=False, indent=2))
    elif command == "canon":
        if args.verdict:
            kernel.emit(me, "canon.ruled", {"id": args.id, "verdict": args.verdict, "note": args.note})
        for canon in kernel.canon(me):
            print(f"  [{canon['status']}] {canon['id']}  {canon['statement']}")
    elif command == "export":
        print(kernel.export(args.audience, args.out))
    elif command == "import-osmax":
        from .importers import import_osmax

        print(import_osmax(kernel, args.repo))
    elif command == "log":
        for event in kernel.events(after=max(0, kernel.ledger.seq - args.n)):
            print(f"{event['seq']:>6} {event['ts']} {event['actor']:<18} {event['type']:<15} {json.dumps(event['data'], ensure_ascii=False)[:90]}")
    return 0


def print_brief(brief: dict[str, Any]) -> None:
    print(f"原力OS · {brief['date']} · {brief['verdict']}\n")
    print(f"待拍板 ({brief['decide_total']})")
    for card in brief["decide"][:15]:
        print(f"  {PRIORITY[card['priority']]}  {card['id']:<24} {card['title'][:40]}  [{card['domain']}]")
    overdue = brief["overdue_total"]
    print(f"\n进行中 ({brief['doing_total']}{f'，{overdue} 项逾期' if overdue else ''})")
    for card in brief["doing"][:10]:
        mark = "!" if card["overdue"] else " "
        print(f"  {mark}   {card['id']:<24} {card['title'][:40]}  due {card['due'] or '—'}")
    calibration = brief["calibration"]
    down = brief["sources"]["down"]
    if brief["sources"]["total"]:
        print(f"\n数据源 {brief['sources']['total']} 个" + (f"，掉线：{', '.join(s['name'] for s in down)}" if down else "，全部正常"))
    else:
        print("\n数据源：本次未采集（运行 yuanli collect）")
    print(f"校准 n={calibration['n']}" + (f" · Brier {calibration['brier']}（0.25=抛硬币）" if calibration["brier"] is not None else ""))


if __name__ == "__main__":
    raise SystemExit(main())
