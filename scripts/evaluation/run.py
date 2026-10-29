"""Paid real-model evaluation. Never runs unless explicitly requested and enabled."""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import agent, store  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--repeat", type=int, default=2, choices=(1, 2))
    args = parser.parse_args()
    if not args.execute or os.environ.get("EVAL_APPROVED") != "yes":
        raise SystemExit("未执行：真实评测需事先确认费用，且必须显式启用。")
    if not all(os.environ.get(k) for k in ("MODEL_API_KEY", "MODEL_BASE_URL", "MODEL_NAME")):
        raise SystemExit("未执行：模型配置不完整。")
    model = os.environ["MODEL_NAME"]
    safe_model = re.sub(r"[^a-zA-Z0-9_.-]", "_", model)[:60]
    cases = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))
    if args.case:
        known = {case["id"] for case in cases}
        if not set(args.case).issubset(known):
            raise SystemExit("未执行：包含未知测试任务。")
        cases = [case for case in cases if case["id"] in args.case]
    rows = []
    with TemporaryDirectory(prefix="qi-shu-eval-") as temp:
        os.environ["AGENT_DB_PATH"] = str(Path(temp) / "eval.sqlite")
        store.init()
        for case in cases:
            for repeat in range(1, args.repeat + 1):
                task = store.create(case["goal"], case["material"])
                started = time.monotonic()
                agent.run(task["id"])
                result = store.get(task["id"])
                rows.append({"case":case["id"], "repeat":repeat, "status":result["status"], "progress":result["progress"], "result":result["result"], "seconds":round(time.monotonic()-started,2), "usage":store.task_usage(task["id"])})
    out_dir = ROOT / "data" / "evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{safe_model}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps({"model":model,"cases":rows},ensure_ascii=False,indent=2), encoding="utf-8")
    print(f"评测记录已保存：{path}")
    print(f"记录 {len(rows)} 次；服务账单与失败请求可能仍有费用，以平台账单为准。")


if __name__ == "__main__":
    main()
