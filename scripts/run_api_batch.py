"""Run paired Dr.Spider experiments through the existing single-sample API runner."""
import argparse
import csv
import hashlib
import random
import re
import subprocess
import sys

from run_api_sample import ROOT, load, make_sample, read_database, save
from baseline import GROUPS


def build_plan(args):
    samples = []
    for group in args.groups:
        folder = ROOT / "data" / group
        before = load(folder / "questions_pre_perturbation.json")
        after = load(folder / "questions_post_perturbation.json")
        if len(before) != len(after):
            raise ValueError(f"{group} 的 pre/post 样本数不同")
        if not 1 <= args.pairs_per_group <= len(before):
            raise ValueError(f"{group} 的抽样对数必须在 1 到 {len(before)} 之间")
        indexes = sorted(
            random.Random(args.seed).sample(range(len(before)), args.pairs_per_group)
        )
        for index in indexes:
            if before[index]["q_id_spider_dev"] != after[index]["q_id_spider_dev"]:
                raise ValueError(f"{group}[{index}] 的 pre/post 原题编号不同")
            for side in ("pre", "post"):
                sample = make_sample(group, index, side)
                read_database(ROOT / sample["database"], sample["gold_sql"])
                samples.append({"run": f"{args.run}-{sample['id']}", "sample": sample})
    return {
        "groups": args.groups, "pairs_per_group": args.pairs_per_group, "seed": args.seed,
        "model": args.model, "metric": "single-database EX",
        "data_source": load(ROOT / "manifests" / "data_source.json"),
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("scripts/run_api_batch.py", "scripts/run_api_sample.py", "src/baseline.py")
        },
        "samples": samples,
    }


def read_outcome(entry, model):
    sample = entry["sample"]
    folder = ROOT / "runs" / entry["run"]
    outcome = {
        "id": sample["id"], "question": sample["question"], "db_id": sample["db_id"],
        "gold_sql": sample["gold_sql"], "pred_sql": "", "correct": None,
        "status": "missing", "error": "", "run": entry["run"],
    }
    if not (folder / "record.json").is_file():
        return outcome

    record = load(folder / "record.json")
    if record["id"] != sample["id"] or load(folder / "sample.json") != sample:
        raise ValueError(f"已有记录的样本与计划不符：{folder}")
    if load(folder / "config.json")["requested_model"] != model:
        raise ValueError(f"已有记录的请求模型与计划不符：{folder}")

    status = record["stage"]
    identity = folder / "model_identity.json"
    if not (folder / "response.json").is_file():
        status = "no_response"
    elif not identity.is_file() or load(identity).get("returned_model") != model:
        status = "unverified_model"
    score = int(record["correct"]) if status in {"done", "execution", "generation"} else None
    return dict(
        outcome, status=status, correct=score,
        pred_sql=record["pred_sql"] or "", error=record["error"] or "",
    )


def write_csv(path, rows):
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def export_results(output, plan):
    pairs = {}
    for entry in plan["samples"]:
        sample = entry["sample"]
        key = (sample["group"], sample["index"])
        row = pairs.setdefault(key, {"group": key[0], "index": key[1]})
        for field, value in read_outcome(entry, plan["model"]).items():
            row[f"{sample['side']}_{field}"] = value

    details = list(pairs.values())
    summary = []
    for group in plan["groups"]:
        rows = [row for row in details if row["group"] == group]
        item = {"group": group, "pairs": len(rows)}
        for side in ("pre", "post"):
            scores = [
                row[f"{side}_correct"] for row in rows if row[f"{side}_correct"] is not None
            ]
            item[f"{side}_scored"] = len(scores)
            item[f"{side}_correct"] = sum(scores)
            item[f"{side}_ex_percent"] = (
                round(100 * sum(scores) / len(rows), 2) if len(scores) == len(rows) else None
            )
        pre = item["pre_ex_percent"]
        post = item["post_ex_percent"]
        item["post_minus_pre_pp"] = (
            round(post - pre, 2) if pre is not None and post is not None else None
        )
        summary.append(item)
    write_csv(output / "per_pair.csv", details)
    write_csv(output / "summary.csv", summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="批次名，改变实验配置时使用新名称")
    parser.add_argument("--groups", nargs="+", choices=GROUPS, default=GROUPS)
    parser.add_argument("--pairs-per-group", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default="gpt-6-sol", help="服务端实际模型 ID")
    parser.add_argument("--execute", action="store_true", help="发送真实 API 生成请求")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run):
        parser.error("--run 只允许字母、数字、下划线和短横线")
    if len(set(args.groups)) != len(args.groups):
        parser.error("--groups 中的类别不能重复")

    plan = build_plan(args)
    output = ROOT / "runs" / args.run
    plan_path = output / "plan.json"
    if plan_path.is_file():
        if load(plan_path) != plan:
            parser.error("已有批次的配置或样本不同，请换 --run")
    else:
        try:
            output.mkdir(parents=True)
        except FileExistsError:
            parser.error("已有同名目录且没有批测清单，请换 --run")
        save(plan_path, plan)
    print(f"已离线检查 {len(plan['samples'])} 条标准 SQL：{plan_path}", flush=True)
    export_results(output, plan)
    if not args.execute:
        return

    runner = ROOT / "scripts" / "run_api_sample.py"
    try:
        for number, entry in enumerate(plan["samples"], 1):
            sample = entry["sample"]
            folder = ROOT / "runs" / entry["run"]
            if not (folder / "record.json").is_file():
                if folder.exists():
                    raise RuntimeError(f"单题目录不完整，请检查：{folder}")
                print(f"[{number}/{len(plan['samples'])}] {sample['id']}", flush=True)
                subprocess.run([
                    sys.executable, "-B", "-X", "utf8", str(runner),
                    "--run", entry["run"], "--model", args.model,
                    "--group", sample["group"], "--index", str(sample["index"]),
                    "--side", sample["side"],
                ], cwd=ROOT, check=False)
            outcome = read_outcome(entry, args.model)
            if outcome["correct"] is None:
                raise RuntimeError(f"{outcome['status']}，请检查：{folder}")
    finally:
        export_results(output, plan)
        print(f"汇总已更新：{output}", flush=True)


if __name__ == "__main__":
    main()
