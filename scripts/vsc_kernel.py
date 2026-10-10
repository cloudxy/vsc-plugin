#!/usr/bin/env python3
"""VSC 工作流内核的稳定查询、契约校验和结构自检接口。

workflow/ 是阶段、角色和跨模块格式的唯一事实来源。本脚本不保存项目状态，也不调用媒体供应商：

  doctor
  route STAGE [--json]
  routes [--json]
  roles [--json]
  contract list [--json]
  contract validate FORMAT FILE
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "workflow"
KERNEL_PATH = WORKFLOW / "kernel.json"
ROLES_PATH = WORKFLOW / "roles.json"
CONTRACTS_PATH = WORKFLOW / "contracts.json"


class KernelError(ValueError):
    """A checked workflow definition is invalid or incomplete."""


def load_json(path):
    try:
        return json.loads(path.read_text("utf-8"))
    except FileNotFoundError as exc:
        raise KernelError(f"缺少内核文件：{path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise KernelError(f"内核 JSON 损坏：{path.relative_to(ROOT)}：{exc}") from exc


def load_kernel():
    data = load_json(KERNEL_PATH)
    if data.get("format") != "vsc.workflow-kernel/v1" or not isinstance(data.get("stages"), list):
        raise KernelError("workflow/kernel.json 必须是 vsc.workflow-kernel/v1 且含 stages 数组")
    return data


def load_roles():
    data = load_json(ROLES_PATH)
    if data.get("format") != "vsc.role-catalog/v1" or not isinstance(data.get("roles"), list):
        raise KernelError("workflow/roles.json 必须是 vsc.role-catalog/v1 且含 roles 数组")
    return data


def load_contracts():
    data = load_json(CONTRACTS_PATH)
    if data.get("format") != "vsc.contract-catalog/v1" or not isinstance(data.get("contracts"), list):
        raise KernelError("workflow/contracts.json 必须是 vsc.contract-catalog/v1 且含 contracts 数组")
    return data


def unique_index(items, key, label):
    index = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get(key), str) or not item[key]:
            raise KernelError(f"{label} 的每一项必须有非空 {key}")
        if item[key] in index:
            raise KernelError(f"{label} {key} 重复：{item[key]}")
        index[item[key]] = item
    return index


def stages():
    return unique_index(load_kernel()["stages"], "id", "stages")


def role_cards():
    return unique_index(load_roles()["roles"], "id", "roles")


def contract_catalog():
    return unique_index(load_contracts()["contracts"], "format", "contracts")


def stage(stage_id):
    try:
        return stages()[stage_id]
    except KeyError as exc:
        raise KernelError("未知工作流阶段「%s」；可用：%s" % (stage_id, "/".join(stages()))) from exc


def vendor_skill_stages():
    return tuple(item["vendor_skill_stage"] for item in stages().values() if item.get("vendor_skill_stage"))


def relative_file(value, label):
    if not isinstance(value, str) or not value:
        raise KernelError(f"{label} 必须是相对文件路径")
    path = (ROOT / value).resolve()
    if ROOT not in path.parents:
        raise KernelError(f"{label} 不能离开插件根目录：{value}")
    return path


def frontmatter(path):
    try:
        lines = path.read_text("utf-8").splitlines()
    except UnicodeDecodeError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    values = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def doctor_problems():
    """Return all structural breaks rather than failing at the first shallow seam."""
    problems = []
    try:
        stage_index = stages()
        roles = role_cards()
        contracts = contract_catalog()
    except KernelError as exc:
        return [str(exc)]

    expected_commands = set()
    expected_skills = set()
    covered_profile_stages = set()
    for stage_id, item in stage_index.items():
        for key in ("command", "skill", "roles", "profile_stages", "contracts"):
            if key not in item:
                problems.append(f"stage {stage_id} 缺字段 {key}")
        command = item.get("command")
        skill = item.get("skill")
        if isinstance(command, str) and command:
            expected_commands.add(command)
            path = ROOT / "commands" / f"{command}.md"
            if not path.is_file():
                problems.append(f"stage {stage_id} 的 command 文件缺失：{path.relative_to(ROOT)}")
            elif frontmatter(path).get("skills") != skill:
                problems.append(f"{path.relative_to(ROOT)} 的 skills 必须为 {skill}")
        else:
            problems.append(f"stage {stage_id}.command 必须是非空字符串")
        if isinstance(skill, str) and skill:
            expected_skills.add(skill)
            path = ROOT / "skills" / skill / "SKILL.md"
            if not path.is_file():
                problems.append(f"stage {stage_id} 的 Skill 文件缺失：{path.relative_to(ROOT)}")
        else:
            problems.append(f"stage {stage_id}.skill 必须是非空字符串")
        for role in item.get("roles", []):
            if role not in roles:
                problems.append(f"stage {stage_id} 引用了未定义角色：{role}")
        for profile_stage in item.get("profile_stages", []):
            if not isinstance(profile_stage, str) or not profile_stage:
                problems.append(f"stage {stage_id}.profile_stages 含非法值")
            else:
                covered_profile_stages.add(profile_stage)
        for contract in item.get("contracts", []):
            if contract not in contracts:
                problems.append(f"stage {stage_id} 引用了未定义契约：{contract}")

    actual_commands = {path.stem for path in (ROOT / "commands").glob("*.md")}
    actual_skills = {path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")}
    for command in sorted(actual_commands - expected_commands):
        problems.append(f"未在 workflow/kernel.json 路由的 command：commands/{command}.md")
    for command in sorted(expected_commands - actual_commands):
        problems.append(f"内核路由但不存在的 command：{command}")
    for skill in sorted(actual_skills - expected_skills):
        problems.append(f"未在 workflow/kernel.json 路由的 Skill：skills/{skill}/SKILL.md")
    for skill in sorted(expected_skills - actual_skills):
        problems.append(f"内核路由但不存在的 Skill：{skill}")

    for role_id, card in roles.items():
        required = ("agent", "identity", "temperament", "authority", "memory_scope", "deliverables")
        for key in required:
            if not card.get(key):
                problems.append(f"role {role_id} 缺字段 {key}")
        try:
            agent = relative_file(card.get("agent"), f"role {role_id}.agent")
        except KernelError as exc:
            problems.append(str(exc))
            continue
        if not agent.is_file():
            problems.append(f"role {role_id} 的 agent 文件缺失：{agent.relative_to(ROOT)}")
        elif frontmatter(agent).get("name") != role_id:
            problems.append(f"{agent.relative_to(ROOT)} 的 name 必须为 {role_id}")

    actual_agents = {path.stem for path in (ROOT / "agents").glob("*.md")}
    known_agents = {Path(card["agent"]).stem for card in roles.values() if isinstance(card.get("agent"), str)}
    for agent in sorted(actual_agents - known_agents):
        problems.append(f"未在 workflow/roles.json 注册的 agent：agents/{agent}.md")
    for agent in sorted(known_agents - actual_agents):
        problems.append(f"角色目录缺少 agent：{agent}")

    artifact_formats = {}
    for format_id, contract in contracts.items():
        for kind in contract.get("artifact_types", []):
            if not isinstance(kind, str) or not kind.startswith("vsc."):
                problems.append(f"contract {format_id}.artifact_types 必须是 vsc.* 类型")
            elif kind in artifact_formats:
                problems.append(f"产物 {kind} 有多个契约：{artifact_formats[kind]} / {format_id}")
            else:
                artifact_formats[kind] = format_id
        template = contract.get("template")
        if template is not None:
            try:
                template_path = relative_file(template, f"contract {format_id}.template")
            except KernelError as exc:
                problems.append(str(exc))
            else:
                if not template_path.is_file():
                    problems.append(f"contract {format_id} 模板缺失：{template}")
                else:
                    try:
                        template_data = json.loads(template_path.read_text("utf-8"))
                    except json.JSONDecodeError as exc:
                        problems.append(f"contract {format_id} 模板 JSON 损坏：{exc}")
                    else:
                        if template_data.get("format") != format_id:
                            problems.append(f"contract {format_id} 模板的 format 不匹配：{template}")
        validator = contract.get("validator")
        if validator is not None:
            if not isinstance(validator, dict) or not isinstance(validator.get("arguments"), list):
                problems.append(f"contract {format_id}.validator 必须含 script 和 arguments")
            else:
                try:
                    script = relative_file(validator.get("script"), f"contract {format_id}.validator.script")
                except KernelError as exc:
                    problems.append(str(exc))
                else:
                    if not script.is_file():
                        problems.append(f"contract {format_id} 校验器缺失：{script.relative_to(ROOT)}")

    for path in sorted((ROOT / "profiles").glob("*.json")):
        try:
            profile = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"Profile JSON 损坏：{path.relative_to(ROOT)}：{exc}")
            continue
        if profile.get("scope_required_from") and profile["scope_required_from"] not in [x.get("id") for x in profile.get("stages", [])]:
            problems.append(f"Profile {path.name} scope_required_from 不属于阶段")
        if profile.get("dependency_policy") not in (None, "explicit", "previous_stage"):
            problems.append(f"Profile {path.name} dependency_policy 必须是 explicit 或 previous_stage")
        for item in profile.get("stages", []):
            profile_stage = item.get("id") if isinstance(item, dict) else None
            if not profile_stage:
                problems.append(f"{path.relative_to(ROOT)} 含无 id 的阶段")
            elif profile_stage not in covered_profile_stages:
                problems.append(f"{path.relative_to(ROOT)} 的阶段 {profile_stage} 没有内核路由")

    # 宿主入口也是物理入口；延迟导入，因为 vsc_hosts 不依赖内核查询接口。
    from vsc_hosts import entry_problems
    from vsc_views import view_problems
    problems.extend(entry_problems())
    problems.extend(view_problems())
    return problems


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def command_doctor(_args):
    problems = doctor_problems()
    if problems:
        print("WORKFLOW DOCTOR: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    from vsc_hosts import load_hosts
    print(f"WORKFLOW DOCTOR: PASS  stages={len(stages())} roles={len(role_cards())} contracts={len(contract_catalog())} hosts={len(load_hosts()[0])}")


def command_route(args):
    result = stage(args.stage)
    if args.json:
        print_json(result)
        return
    print(f"{result['id']}: /{result['command']} → {result['skill']}  roles={','.join(result['roles'])}")
    if result.get("contracts"):
        print("contracts=" + ",".join(result["contracts"]))
    if result.get("vendor_skill_stage"):
        print("vendor_skill_stage=" + result["vendor_skill_stage"])


def command_routes(args):
    values = list(stages().values())
    if args.json:
        print_json(values)
        return
    for item in values:
        print(f"{item['id']:<12} /{item['command']:<18} {item['skill']}")


def command_roles(args):
    values = list(role_cards().values())
    if args.json:
        print_json(values)
        return
    for card in values:
        print(f"{card['id']:<24} {card['identity']}")


def command_contract_list(args):
    values = list(contract_catalog().values())
    if args.json:
        print_json(values)
        return
    for contract in values:
        validator = contract.get("validator")
        implementation = validator["script"] if validator else "generated/no standalone validator"
        print(f"{contract['format']:<34} {implementation}")


def command_contract_validate(args):
    try:
        contract = contract_catalog()[args.format]
    except KeyError as exc:
        raise KernelError("未知契约格式「%s」；运行 contract list 查看可用项" % args.format) from exc
    validator = contract.get("validator")
    if not validator:
        raise KernelError(f"{args.format} 没有独立校验器；它由 {contract.get('owner', '其拥有者')} 生成")
    script = relative_file(validator.get("script"), f"contract {args.format}.validator.script")
    if not script.is_file():
        raise KernelError(f"校验器不存在：{script.relative_to(ROOT)}")
    result = subprocess.run([sys.executable, "-B", str(script), *validator["arguments"], args.file])
    raise SystemExit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="检查流程内核与物理入口是否完整").set_defaults(fn=command_doctor)
    route_parser = commands.add_parser("route", help="查询一个阶段的真实路由")
    route_parser.add_argument("stage")
    route_parser.add_argument("--json", action="store_true")
    route_parser.set_defaults(fn=command_route)
    routes_parser = commands.add_parser("routes", help="列出所有阶段")
    routes_parser.add_argument("--json", action="store_true")
    routes_parser.set_defaults(fn=command_routes)
    roles_parser = commands.add_parser("roles", help="列出角色卡")
    roles_parser.add_argument("--json", action="store_true")
    roles_parser.set_defaults(fn=command_roles)
    contract_parser = commands.add_parser("contract", help="查询或校验跨模块 JSON 契约")
    contract_commands = contract_parser.add_subparsers(dest="contract_command", required=True)
    list_parser = contract_commands.add_parser("list")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(fn=command_contract_list)
    validate_parser = contract_commands.add_parser("validate")
    validate_parser.add_argument("format")
    validate_parser.add_argument("file")
    validate_parser.set_defaults(fn=command_contract_validate)
    args = parser.parse_args()
    try:
        args.fn(args)
    except KernelError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
