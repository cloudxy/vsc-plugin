#!/usr/bin/env python3
"""VSC 本地 CI：维护者把改动提交并推送 main 前，在本机运行。

vendor/ 与 projects/ 只存在于维护者本机，线上环境无法复现，因此 VSC 不使用线上 CI。依次检查：

  doctor    工作流内核与物理入口
  tests     scripts/test_*.py 全部测试
  vendor    锁定文件、已安装版本与各阶段路由的上游 Skill
  projects  projects/ 中每个作品仍能被当前状态机读取
  tracked   Git 跟踪文件不含作品、vendor 源码或本机配置

只读：不联网、不下载、不写作品状态。全部通过时退出码为 0。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import vendor_skills
from vsc_kernel import doctor_problems

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VENDOR = ROOT / "vendor"
PROJECTS = ROOT / "projects"
# 与 .gitignore 保持一致：vendor/ 只跟踪这三份声明，其余为本机内容。
TRACKED_VENDOR = {"vendor/README.md", "vendor/sources.lock.json", "vendor/THIRD_PARTY.md"}
LOCAL_ONLY = (".claude/settings.local.json", ".zcodeignore", ".video_agent/", ".idea/")


def run(*args):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True)


def tail(result, lines=30):
    output = (result.stdout + result.stderr).strip().splitlines()
    return output[-lines:] or [f"exit {result.returncode}"]


def check_doctor():
    return "", doctor_problems()


def check_tests():
    result = run(sys.executable, "-B", "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_*.py")
    summary = next((line for line in result.stderr.splitlines() if line.startswith("Ran ")), "")
    return summary, tail(result) if result.returncode else []


def installed_problems(sources, vendor_root=VENDOR):
    """每个锁定来源都须在本机安装，且检出版本与锁定 revision 一致。"""
    problems = []
    for source in sources:
        source_id, revision = source["id"], source["revision"].lower()
        path = vendor_root / source_id
        if not path.is_dir():
            problems.append(f"{source_id} 未安装：python3 -B scripts/vendor_sync.py --install {source_id}")
            continue
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, capture_output=True)
        actual = head.stdout.strip().lower()
        if head.returncode or actual != revision:
            problems.append(f"{source_id} 本机版本 {actual[:12] or '未知'} 与锁定 {revision[:12]} 不一致")
    return problems


def route_problems(vendor_root=VENDOR):
    problems = []
    for stage in vendor_skills.STAGES:
        try:
            records = vendor_skills.resolve(stage, vendor_root)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        problems.extend(
            f"阶段 {stage} 路由的上游 Skill 缺失：{record['relative_path']}"
            for record in records if record["readiness"].startswith("missing")
        )
    return problems


def check_vendor():
    result = run(sys.executable, "-B", str(HERE / "vendor_sync.py"), "--check")
    if result.returncode:
        return "", tail(result)
    sources = json.loads((VENDOR / "sources.lock.json").read_text("utf-8"))["sources"]
    problems = installed_problems(sources) + route_problems()
    return f"{len(sources)} 个来源，{len(vendor_skills.STAGES)} 个阶段路由", problems


def project_problems(projects_root=PROJECTS):
    """作品数据是发现问题的来源：工作流改动后，已有作品必须仍能被读取（或明确需要迁移）。"""
    projects = sorted(state.parent for state in projects_root.glob("*/vsc.json"))
    problems = []
    for project in projects:
        result = run(sys.executable, "-B", str(HERE / "vsc_state.py"), "status", str(project))
        if result.returncode:
            problems.append(f"作品 {project.name} 无法被当前状态机读取：{tail(result, 1)[0]}")
    return projects, problems


def check_projects():
    projects, problems = project_problems()
    return f"{len(projects)} 个作品", problems


def tracked_problems(paths):
    problems = []
    for path in paths:
        if path.startswith("projects/"):
            problems.append(f"作品数据被 Git 跟踪：{path}")
        elif path.startswith("vendor/") and path not in TRACKED_VENDOR:
            problems.append(f"vendor 源码被 Git 跟踪：{path}")
        elif path.startswith(LOCAL_ONLY) or path.rsplit("/", 1)[-1] == ".DS_Store" or "__pycache__/" in path:
            problems.append(f"本机文件被 Git 跟踪：{path}")
    return problems


def check_tracked():
    result = run("git", "ls-files", "-z")
    if result.returncode:
        return "", tail(result)
    paths = [path for path in result.stdout.split("\0") if path]
    return f"{len(paths)} 个跟踪文件", tracked_problems(paths)


CHECKS = (
    ("doctor", check_doctor),
    ("tests", check_tests),
    ("vendor", check_vendor),
    ("projects", check_projects),
    ("tracked", check_tracked),
)


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    failed = 0
    for name, check in CHECKS:
        detail, problems = check()
        print(f"{'FAIL' if problems else 'PASS'} {name:<9} {detail}".rstrip(), flush=True)
        for problem in problems:
            print(f"  - {problem}")
        failed += bool(problems)
    if failed:
        print(f"LOCAL CI: FAIL（{failed} 项）")
        raise SystemExit(1)
    print("LOCAL CI: PASS")


if __name__ == "__main__":
    main()
