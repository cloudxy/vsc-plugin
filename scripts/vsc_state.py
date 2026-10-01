#!/usr/bin/env python3
"""VSC 项目状态机：通用短剧／短视频工作流的确定性状态与质量门。

VSC 是独立插件。它不执行供应商 API，不读取或调用其他插件；来源可以是小说、原创文本、品牌资料，
或符合 creative-handoff/v1 的外部交接包。

  init <project> --title T [--profile vsc.narrative-base|vsc.novel-serial|vsc.brand-story] [--owner O]
  status <project> | next <project>
  source add <project> --kind novel|original|brief|reference --file F
  source import <project> --manifest creative-handoff.json
  artifact add <project> --type vsc.TYPE --stage STAGE --file F [--depends ID ...] [--note N]
  artifact decide <project> ID --status approved|rejected --by NAME [--note N]
  artifact list <project> [--stage STAGE] [--type TYPE]
  decision add <project> --kind K --target ID --outcome accepted|rejected|deferred --by NAME --reason R
  gate check <project> STAGE
  profile list | profile show PROFILE
  handoff validate MANIFEST

状态权威是项目目录中的 vsc.json；创作产物是文件，状态只由本脚本写入。
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

SCHEMA = 1
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PLUGIN_ROOT / "profiles"
STATE_FILE = "vsc.json"
HANDOFF_FORMAT = "creative-handoff/v1"
ARTIFACT_STATES = ("draft", "review", "approved", "rejected")
SOURCE_KINDS = ("novel", "original", "brief", "reference")
PROJECT_DIRS = (
    "00-委托", "01-来源", "02-改编", "03-剧本", "04-视听设计/角色", "04-视听设计/场景",
    "04-视听设计/动作", "04-视听设计/声音", "04-视听设计/镜头", "05-预演", "06-素材/图像",
    "06-素材/视频", "06-素材/音频", "07-后期", "08-交付", "09-台账",
)


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def die(message, code=1):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.write("\n")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        die(f"JSON 损坏：{path}：{exc}")


def sha16(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else ""


def profile_catalog():
    result = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        data = read_json(path, {})
        if data.get("profile_id"):
            result[data["profile_id"]] = data
    return result


def profile_for(profile_id):
    profile = profile_catalog().get(profile_id)
    if not profile:
        die(f"未知 Profile「{profile_id}」；运行 profile list 查看可用项")
    return profile


def project_state(project: Path):
    state = read_json(project / STATE_FILE)
    if not state:
        die(f"缺 {STATE_FILE}：{project}（先运行 init）")
    if state.get("schema_version") != SCHEMA:
        die(f"{STATE_FILE} schema {state.get('schema_version')} 不受当前版本支持")
    profile_for(state.get("profile_id"))
    return state


def save(project: Path, state):
    state["updated_at"] = now()
    write_json(project / STATE_FILE, state)


def next_id(items, prefix):
    greatest = 0
    for item in items:
        value = str(item.get("id", ""))
        if value.startswith(prefix + "-"):
            try:
                greatest = max(greatest, int(value.rsplit("-", 1)[1]))
            except ValueError:
                pass
    return f"{prefix}-{greatest + 1:04d}"


def rel_or_abs(path: Path, project: Path):
    try:
        return str(path.resolve().relative_to(project.resolve()))
    except ValueError:
        return str(path.resolve())


def artifact_by_id(state, artifact_id):
    artifact = next((x for x in state["artifacts"] if x["id"] == artifact_id), None)
    if not artifact:
        die(f"没有产物 {artifact_id}")
    return artifact


def stage_for(profile, stage_id):
    stage = next((x for x in profile["stages"] if x["id"] == stage_id), None)
    if not stage:
        die("未知阶段「%s」；可用：%s" % (stage_id, "/".join(x["id"] for x in profile["stages"])))
    return stage


def gate_problems(project: Path, state, stage_id):
    profile = profile_for(state["profile_id"])
    stage_index = next((i for i, x in enumerate(profile["stages"]) if x["id"] == stage_id), None)
    if stage_index is None:
        stage_for(profile, stage_id)
    required = []
    for stage in profile["stages"][:stage_index + 1]:
        required.extend((stage["id"], kind) for kind in stage.get("required", []))
    problems = []
    if stage_index >= 1 and not state["sources"]:
        problems.append("尚未登记来源（source add 或 source import）")
    for owner_stage, kind in required:
        candidates = [x for x in state["artifacts"] if x.get("type") == kind and x.get("status") == "approved"]
        if not candidates:
            problems.append(f"{owner_stage} 缺已批准产物：{kind}")
    return problems


def first_open_stage(project: Path, state):
    profile = profile_for(state["profile_id"])
    for stage in profile["stages"]:
        if gate_problems(project, state, stage["id"]):
            return stage
    return None


def append_event(state, event, **fields):
    state["events"].append({"id": next_id(state["events"], "E"), "at": now(), "event": event, **fields})


def template_files(project: Path):
    templates = {
        "00-委托/创作委托.md": "# 创作委托\n\n## 目标\n\n（待填写）\n\n## 受众与格式\n\n（待填写）\n\n## 成功条件与约束\n\n（待填写）\n",
        "01-来源/来源说明.md": "# 来源说明\n\n来源文件由 `source add` 或 `source import` 登记；将原文事实、人物说法、解释、改编和新增内容分开记录。\n",
        "02-改编/改编契约.md": "# 改编契约\n\n## 不可改\n\n（待填写）\n\n## 可调整\n\n（待填写）\n\n## 新增原则\n\n（待填写）\n",
        "04-视听设计/镜头/镜头表.md": "# 镜头表\n\n每镜写清：叙事目的、景别、机位、运镜、构图、角色与动作、声音提示、转场、参考资产与时长。\n",
        "09-台账/README.md": "# VSC 台账\n\n`vsc.json` 是项目状态权威。每份文件产物以版本、新鲜度、依赖和批准决定进入状态；不要在这里把草稿直接当作已批准基线。\n",
    }
    for rel, content in templates.items():
        path = project / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, "utf-8")


def cmd_init(args):
    project = Path(args.project)
    if (project / STATE_FILE).exists():
        die(f"已存在 {project / STATE_FILE}，拒绝覆盖")
    profile = profile_for(args.profile)
    for rel in PROJECT_DIRS:
        (project / rel).mkdir(parents=True, exist_ok=True)
    template_files(project)
    state = {
        "schema_version": SCHEMA,
        "project_id": f"vsc-project-{uuid.uuid4().hex}",
        "title": args.title,
        "profile_id": profile["profile_id"],
        "profile_version": profile.get("version", ""),
        "owner": args.owner or "",
        "sources": [], "artifacts": [], "decisions": [], "events": [],
        "created_at": now(), "updated_at": now(),
    }
    append_event(state, "project_initialized", profile=profile["profile_id"], owner=state["owner"])
    save(project, state)
    print(f"OK VSC 项目已建立：{project}  profile={profile['profile_id']}")


def cmd_status(args):
    project = Path(args.project)
    state = project_state(project)
    profile = profile_for(state["profile_id"])
    open_stage = first_open_stage(project, state)
    approved = sum(1 for x in state["artifacts"] if x["status"] == "approved")
    print(f"项目: {state['title']}  Profile: {profile['label']}  Owner: {state['owner'] or '未设'}")
    print(f"来源: {len(state['sources'])}  产物: {len(state['artifacts'])}（已批准 {approved}）  决策: {len(state['decisions'])}")
    if open_stage:
        gaps = gate_problems(project, state, open_stage["id"])
        print(f"下一关: {open_stage['id']}「{open_stage['label']}」")
        for item in gaps:
            print(f"  - {item}")
    else:
        print("所有 Profile 交付关已满足；仍应按项目策略完成人工审片与对外交付授权。")
    print(f"更新于: {state['updated_at']}")


def cmd_next(args):
    project = Path(args.project)
    state = project_state(project)
    stage = first_open_stage(project, state)
    if not stage:
        print("DONE")
        return
    print(stage["id"])


def cmd_source(args):
    project = Path(args.project)
    state = project_state(project)
    if args.action == "add":
        if args.kind not in SOURCE_KINDS:
            die("--kind 只能是 " + "/".join(SOURCE_KINDS))
        path = Path(args.file)
        if not path.is_file():
            die(f"来源文件不存在：{path}")
        source = {"id": next_id(state["sources"], "S"), "kind": args.kind, "path": rel_or_abs(path, project),
                  "sha256_16": sha16(path), "added_at": now()}
        state["sources"].append(source)
        append_event(state, "source_registered", source_id=source["id"], kind=args.kind)
        save(project, state)
        print(f"OK {source['id']} 来源已登记（{args.kind}）")
        return
    manifest = Path(args.manifest)
    package = validate_handoff(manifest)
    source = {"id": next_id(state["sources"], "S"), "kind": "handoff", "path": rel_or_abs(manifest, project),
              "sha256_16": sha16(manifest), "package_id": package["package_id"], "added_at": now()}
    state["sources"].append(source)
    append_event(state, "handoff_imported", source_id=source["id"], package_id=package["package_id"])
    save(project, state)
    print(f"OK {source['id']} 已登记外部交接包 {package['package_id']}；请审阅后把需要的内容登记为本项目产物。")


def cmd_artifact(args):
    project = Path(args.project)
    state = project_state(project)
    profile = profile_for(state["profile_id"])
    if args.action == "list":
        for item in state["artifacts"]:
            if args.stage and item["stage"] != args.stage:
                continue
            if args.type and item["type"] != args.type:
                continue
            print(f"{item['id']} [{item['status']}] {item['stage']} {item['type']}  {item['path']}")
        return
    if args.action == "add":
        stage_for(profile, args.stage)
        if not args.type.startswith("vsc."):
            die("--type 必须以 vsc. 开头，避免业务字段污染通用协议")
        path = Path(args.file)
        if not path.is_file():
            die(f"产物文件不存在：{path}")
        deps = args.depends or []
        for dependency in deps:
            artifact_by_id(state, dependency)
        item = {"id": next_id(state["artifacts"], "A"), "type": args.type, "stage": args.stage,
                "path": rel_or_abs(path, project), "sha256_16": sha16(path), "depends_on": deps,
                "note": args.note or "", "status": "draft", "created_at": now(), "decision": None}
        state["artifacts"].append(item)
        append_event(state, "artifact_registered", artifact_id=item["id"], type=item["type"], stage=item["stage"])
        save(project, state)
        print(f"OK {item['id']} 产物已登记为 draft")
        return
    item = artifact_by_id(state, args.id)
    item["status"] = args.status
    item["decision"] = {"by": args.by, "note": args.note or "", "at": now()}
    append_event(state, "artifact_decided", artifact_id=item["id"], status=args.status, by=args.by)
    save(project, state)
    print(f"OK {item['id']} → {args.status}（{args.by}）")


def cmd_decision(args):
    project = Path(args.project)
    state = project_state(project)
    artifact_by_id(state, args.target)
    if not args.reason.strip():
        die("决策必须写 --reason，保留选择依据")
    item = {"id": next_id(state["decisions"], "D"), "kind": args.kind, "target": args.target,
            "outcome": args.outcome, "by": args.by, "reason": args.reason, "at": now()}
    state["decisions"].append(item)
    append_event(state, "decision_recorded", decision_id=item["id"], target=args.target, outcome=args.outcome)
    save(project, state)
    print(f"OK {item['id']} 已记录")


def cmd_gate(args):
    project = Path(args.project)
    state = project_state(project)
    problems = gate_problems(project, state, args.stage)
    if problems:
        print(f"GATE {args.stage}: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    print(f"GATE {args.stage}: PASS")


def validate_handoff(path: Path):
    if not path.is_file():
        die(f"交接包清单不存在：{path}")
    package = read_json(path, {})
    required = ("format", "package_id", "source", "artifacts", "decisions")
    missing = [key for key in required if key not in package]
    if package.get("format") != HANDOFF_FORMAT:
        die(f"交接包格式必须是 {HANDOFF_FORMAT}（当前：{package.get('format') or '未填'}）")
    if missing:
        die("交接包缺字段：" + "、".join(missing))
    if not isinstance(package["artifacts"], list) or not isinstance(package["decisions"], list):
        die("交接包 artifacts 与 decisions 必须为数组")
    return package


def cmd_handoff(args):
    package = validate_handoff(Path(args.manifest))
    print(f"HANDOFF: PASS  package={package['package_id']} artifacts={len(package['artifacts'])} decisions={len(package['decisions'])}")


def cmd_profile(args):
    catalog = profile_catalog()
    if args.action == "list":
        for profile_id, profile in catalog.items():
            print(f"{profile_id}  {profile.get('label', '')}  v{profile.get('version', '')}")
        return
    profile = profile_for(args.profile_id)
    print(f"{profile['profile_id']} · {profile['label']} · v{profile.get('version', '')}")
    for stage in profile["stages"]:
        print(f"  {stage['id']} {stage['label']}：{'、'.join(stage.get('required', []))}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("init"); p.add_argument("project"); p.add_argument("--title", required=True)
    p.add_argument("--profile", default="vsc.narrative-base"); p.add_argument("--owner"); p.set_defaults(fn=cmd_init)
    for name, fn in (("status", cmd_status), ("next", cmd_next)):
        p = commands.add_parser(name); p.add_argument("project"); p.set_defaults(fn=fn)
    p = commands.add_parser("source"); subs = p.add_subparsers(dest="action", required=True)
    q = subs.add_parser("add"); q.add_argument("project"); q.add_argument("--kind", required=True); q.add_argument("--file", required=True)
    q = subs.add_parser("import"); q.add_argument("project"); q.add_argument("--manifest", required=True)
    p.set_defaults(fn=cmd_source)
    p = commands.add_parser("artifact"); subs = p.add_subparsers(dest="action", required=True)
    q = subs.add_parser("add"); q.add_argument("project"); q.add_argument("--type", required=True); q.add_argument("--stage", required=True)
    q.add_argument("--file", required=True); q.add_argument("--depends", action="append"); q.add_argument("--note")
    q = subs.add_parser("decide"); q.add_argument("project"); q.add_argument("id"); q.add_argument("--status", choices=("approved", "rejected"), required=True)
    q.add_argument("--by", required=True); q.add_argument("--note")
    q = subs.add_parser("list"); q.add_argument("project"); q.add_argument("--stage"); q.add_argument("--type")
    p.set_defaults(fn=cmd_artifact)
    p = commands.add_parser("decision"); subs = p.add_subparsers(dest="action", required=True)
    q = subs.add_parser("add"); q.add_argument("project"); q.add_argument("--kind", required=True); q.add_argument("--target", required=True)
    q.add_argument("--outcome", choices=("accepted", "rejected", "deferred"), required=True); q.add_argument("--by", required=True); q.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_decision)
    p = commands.add_parser("gate"); subs = p.add_subparsers(dest="action", required=True)
    q = subs.add_parser("check"); q.add_argument("project"); q.add_argument("stage")
    p.set_defaults(fn=cmd_gate)
    p = commands.add_parser("handoff"); subs = p.add_subparsers(dest="action", required=True)
    q = subs.add_parser("validate"); q.add_argument("manifest")
    p.set_defaults(fn=cmd_handoff)
    p = commands.add_parser("profile"); subs = p.add_subparsers(dest="action", required=True)
    subs.add_parser("list")
    q = subs.add_parser("show"); q.add_argument("profile_id")
    p.set_defaults(fn=cmd_profile)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
