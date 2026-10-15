#!/usr/bin/env python3
"""只读制作工具就绪诊断：文件实现、配置存在性、项目候选证据与待人工审阅分别报告。"""
from vsc.bootstrap import repository_root, script_path
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from vsc.story import consistency as C
from vsc.adapters.providers.volc_ark import api as A
from vsc.adapters.providers import credentials as credentials
from vsc.assets import library as L

ROOT = repository_root()
FORMAT = "vsc.toolchain-readiness/v1"
ENV_NAMES = (credentials.KEY_ENV,)
# Agent Plan 规则禁止用该 key 直接调用文本生成模型；视觉检查虽已实现，但不能用统一 key 提交。
BLOCKED = {"ark_visual": credentials.TEXT_MODELS_FORBIDDEN}
IGNORED_DIRS = {"废弃", ".vsc-production", "09-台账", "10-记忆", "node_modules", "build"}
# provider/kind 仅用于分类已经核验的项目证据，不能据配置推定权限。
TOOLS = (
    ("ark_image", "豆包图像", "volc_ark.py", ENV_NAMES, "volcengine_ark", "image"),
    ("ark_video", "豆包视频", "volc_ark.py", ENV_NAMES, "volcengine_ark", "video"),
    ("ark_visual", "豆包视觉检查", "volc_ark.py", ENV_NAMES, None, None),
    ("doubao_speech", "豆包语音", "doubao_speech.py", ENV_NAMES, "doubao_speech", "audio"),
    ("seed_audio", "SeedAudio", "doubao_audio.py", ENV_NAMES, "doubao_audio", "audio"),
    ("procedural_audio", "本地原创程序声音", "procedural_audio.py", (), "vsc_procedural_audio", "audio"),
    ("queue", "有界生产队列", "vsc_production.py", (), None, None),
    ("recipes", "原生制作规格", "vsc_recipes.py", (), None, None),
    ("craft", "创作方法卡", "vsc_craft.py", (), None, None),
    ("sequence", "镜头续接", "vsc_sequence.py", (), None, None),
)


def load_json(path):
    return json.loads(Path(path).read_text("utf-8"))


def media_matches(project, items):
    """复用 adapter 的项目内路径与 SHA 验证；不解码、不提交、不声称审美通过。"""
    return A.checked_outputs({"outputs": items}, project)


def schema_errors(checker, value):
    try:
        return checker(value)
    except (TypeError, KeyError, ValueError, AttributeError):
        return ["嵌套字段类型无效"]


def active_json_paths(project):
    """剪枝后扫描活跃目录；不进入废弃、快照、缓存或符号链接目录。"""
    for folder, directories, filenames in os.walk(project, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in IGNORED_DIRS and not name.startswith("."))
        for name in sorted(filenames):
            if name.endswith(".json"):
                yield Path(folder) / name


def project_evidence(project, errors):
    project = Path(project).resolve()
    result = {"project_id": None, "verified_candidates": [], "verified_visual_reports": [], "rejected": []}
    if not project.is_dir():
        errors.append({"path": str(project), "reason": "作品目录不存在或不是目录"})
        return result
    state = project / "vsc.json"
    if not state.resolve().is_relative_to(project):
        errors.append({"path": "vsc.json", "reason": "作品索引通过符号链接越界"})
        return result
    try:
        value = load_json(state)
        if not isinstance(value, dict) or not C.text(value.get("project_id")):
            raise ValueError("project_id 无效")
        result["project_id"] = value["project_id"]
    except (OSError, ValueError):
        errors.append({"path": "vsc.json", "reason": "作品索引不存在、无法读取或 project_id 无效"})
        return result
    # 仅在用户指定作品内发现证据。不读取别的作品或聊天记忆，不写索引。
    seen = set()
    for path in active_json_paths(project):
        relative_path = path.relative_to(project)
        relative = str(relative_path)
        named_record = path.name.endswith("生成记录.json")
        named_visual = path.name.endswith("视觉检查.json")
        if not path.resolve().is_relative_to(project):
            if named_record or named_visual:
                errors.append({"path": relative, "reason": "证据文件通过符号链接越界"})
            continue
        try:
            value = load_json(path)
        except (OSError, ValueError):
            if named_record or named_visual:
                errors.append({"path": relative, "reason": "证据 JSON 无法读取"})
            continue
        kind = value.get("format") if isinstance(value, dict) else None
        if kind not in (C.RECORD_FORMAT, C.VISUAL_FORMAT):
            if named_record or named_visual:
                result["rejected"].append({"path": relative, "reason": "legacy/non-contract"})
            continue
        problems = schema_errors(C.record_errors if kind == C.RECORD_FORMAT else C.visual_errors, value)
        if problems:
            result["rejected"].append({"path": relative, "reason": "invalid_schema"})
            errors.append({"path": relative, "reason": "证据 schema 无效", "details": problems})
            continue
        if value["project_id"] != result["project_id"]:
            result["rejected"].append({"path": relative, "reason": "foreign_project"})
            continue
        if kind == C.RECORD_FORMAT and (value["status"] != "succeeded" or value.get("errors")):
            result["rejected"].append({"path": relative, "reason": "not_successful_without_errors"})
            continue
        items = value["outputs"] if kind == C.RECORD_FORMAT else [value["subject"]]
        try:
            matched = media_matches(project, items)
        except (A.ArkError, OSError, ValueError, TypeError, KeyError):
            matched = False
        if not matched:
            result["rejected"].append({"path": relative, "reason": "media_missing_or_sha_mismatch"})
            errors.append({"path": relative, "reason": "证据媒体缺失、路径越界或 SHA-256 不一致"})
            continue
        # 同一记录的快照/副本只计一次。去重只在内存发生，不创建 registry。
        digest = A.digest_json(value)
        if digest in seen:
            continue
        seen.add(digest)
        if kind == C.RECORD_FORMAT:
            result["verified_candidates"].append({"record": relative, "provider": value["engine"]["provider"],
                "kind": value["kind"], "output_count": len(items), "record_sha256": A.sha256(path)})
        else:
            result["verified_visual_reports"].append({"report": relative, "provider": value["engine"]["provider"],
                "subject_sha256": value["subject"]["sha256"], "advisory": True})
    return result


def library_inventory(root, errors):
    root = L.library_root(root)
    kinds, rights = L.taxonomy()
    counts = {kind: {"label": value["label"], "media_count": 0, "specification_count": 0, "other_count": 0}
              for kind, value in kinds.items()}
    result = {"path": str(root), "exists": root.is_dir(), "kinds": counts,
              "media_count": 0, "specification_count": 0, "other_count": 0,
              "note": "条目完整性与文件 SHA 统计；不证明授权、不替代人工选择。规格不计作媒体。"}
    if not root.exists():
        return result
    if not root.is_dir():
        errors.append({"path": str(root), "reason": "素材库不是目录"})
        return result
    try:
        items = L.load_items(root)
    except (L.LibraryError, OSError, ValueError):
        errors.append({"path": str(root), "reason": "素材库条目 JSON 无法读取"})
        return result
    seen = set()
    for folder, item in items:
        label = str(folder.relative_to(root))
        try:
            if not folder.resolve().is_relative_to(root.resolve()):
                raise L.LibraryError("条目目录越界")
            L.checked_item(folder, item, kinds, rights)
            if item["id"] in seen or folder.name != item["id"] or folder.parent.name != item["kind"]:
                raise L.LibraryError("ID重复或目录不匹配")
            seen.add(item["id"])
        except (L.LibraryError, OSError, ValueError, TypeError, KeyError):
            errors.append({"path": "library/" + label, "reason": "素材库条目无效、重复、文件缺失或 SHA-256 不一致"})
            continue
        attrs = item.get("attributes", {})
        specification = (attrs.get("asset_type") == "specification" or attrs.get("rights_scope") == "specification_only"
                         or attrs.get("is_media") is False)
        category = "specification_count" if specification else "media_count" if item.get("files") else "other_count"
        counts[item["kind"]][category] += 1
        result[category] += 1
    return result


def redact(value):
    """报告不包含密钥值；即使不可信证据把密钥写进字段，也只报告掩码。"""
    secrets = [os.environ[name] for name in ENV_NAMES if os.environ.get(name)]
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def readiness(project, library=None):
    errors = []
    evidence = project_evidence(project, errors)
    inventory = library_inventory(library, errors)
    tools = []
    for identifier, label, script, names, provider, kind in TOOLS:
        present = [name for name in names if bool(os.environ.get(name))]
        records = [entry["record"] for entry in evidence["verified_candidates"]
                   if provider and entry["provider"] == provider and entry["kind"] == kind]
        visual = [entry["report"] for entry in evidence["verified_visual_reports"]
                  if identifier == "ark_visual" and entry["provider"] == "volcengine_ark"]
        blocked = BLOCKED.get(identifier)
        tools.append({"id": identifier, "label": label, "script": "scripts/" + script,
            "implemented": (ROOT / "scripts" / script).is_file(),
            "configured": False if blocked else bool(present) if names else True,
            "configuration": {"status": "blocked_by_plan_rules" if blocked else "present" if present
                              else "pending" if names else "not_required",
                              "any_env_names": list(names), "present_env_names": present,
                              "blocked_reason": blocked,
                              "missing_hint": (credentials.key_problem() if names and not present else None)},
            "permission_verification": "not_probed", "verified_candidates": {"count": len(records), "records": records},
            "verified_visual_reports": {"count": len(visual), "reports": visual}, "human_review": "pending"})
    for name in ("ffmpeg", "ffprobe"):
        available = shutil.which(name) is not None
        tools.append({"id": name, "label": name, "implemented": available, "configured": available,
            "configuration": {"status": "local_executable_present" if available else "pending"},
            "permission_verification": "not_probed", "verified_candidates": {"count": 0, "records": []},
            "human_review": "pending"})
    report = {"format": FORMAT, "project": str(Path(project).resolve()), "project_id": evidence["project_id"],
        "read_only": True, "network_probed": False, "human_review": "pending", "approval_granted": False,
        "meaning": {"implemented": "脚本文件或本地可执行文件存在；不代表功能已运行。",
                    "configured": "仅凭环境变量存在性；本地无凭证工具为 not_required；不验证模型权限、账户、额度或供应商可用性。",
                    "verified_candidates": "仅统计本作品 schema 有效、succeeded 且无 errors、实际输出 SHA 一致的生成记录；不是人工批准。",
                    "verified_visual_reports": "仅核报告 schema 和 subject SHA；AI 视觉建议不属于生成记录，也不批准作品。",
                    "active_scan": "跳过废弃、.vsc-production、09-台账、10-记忆、node_modules、build 和点开头目录；旧非契约记录仅列 rejected，不证明可用。"},
        "tools": tools, "project_evidence": evidence, "library": inventory, "errors": errors}
    return redact(report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--library")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = readiness(args.project, args.library)
    except (OSError, ValueError, TypeError, L.LibraryError) as exc:
        # 只报告异常类型，不回显未知文件中可能携带的密钥或内容。
        report = {"format": FORMAT, "read_only": True, "network_probed": False, "human_review": "pending",
                  "approval_granted": False, "errors": [{"reason": "诊断输入无效", "type": type(exc).__name__}]}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("只读制作就绪诊断：配置存在性不等于权限验证；无网络探测，不批准作品；人工审阅 pending。")
        for tool in report.get("tools", []):
            count = tool["verified_candidates"]["count"]
            visual = tool.get("verified_visual_reports", {}).get("count", 0)
            config = tool["configuration"]
            names = "|".join(config.get("any_env_names", [])) or "无需凭证"
            present = "|".join(config.get("present_env_names", [])) or "无"
            print(f"{tool['id']}: implemented={tool['implemented']} configured={tool['configured']} "
                  f"configuration={config['status']} env={names} present_env={present} "
                  f"verified_candidates={count} visual_reports={visual} human_review=pending")
            if config.get("missing_hint"):
                print(f"  {names}：{config['missing_hint']}")
        for kind, values in report.get("library", {}).get("kinds", {}).items():
            print(f"素材 {kind}: media={values['media_count']} specification={values['specification_count']} other={values['other_count']}")
        for error in report["errors"]:
            print(f"ERROR: {error.get('path', '')} {error['reason']}", file=sys.stderr)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
