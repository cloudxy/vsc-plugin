#!/usr/bin/env python3
"""VSC 宿主入口：从唯一来源生成各 AI 客户端的发现入口。

workflow/hosts.json 声明每个宿主读取哪些入口。本脚本从 skills/、agents/ 与 workflow/kernel.json
生成这些入口（软链接、Codex 角色 TOML、ZCode 插件命令）；入口不手改：

  list [--json]   每个宿主能发现的说明文件、技能、角色与命令
  sync            生成或更新全部入口，删除多余的生成项
  check           只检查不写入；入口与来源不一致时退出码为 1
"""
from vsc.bootstrap import repository_root
import argparse
import json
import os
import re
from pathlib import Path

ROOT = repository_root()
FORMAT = "vsc.hosts/v1"
# 每种入口格式能从哪些来源生成。
SOURCES = {"link": ("skills",), "role-markdown": ("agents",), "codex-toml": ("agents",), "plugin-command": ("stages",)}
SOURCE_LABELS = {"skills": "技能", "agents": "角色", "stages": "命令"}
FORMAT_LABELS = {"link": "软链接", "role-markdown": "完整角色提示", "codex-toml": "Codex TOML", "plugin-command": "插件命令"}
GENERATED = "由 scripts/kernel/hosts.py 生成，勿手改"


class HostError(ValueError):
    """宿主声明或其来源无效，无法计算入口。"""


def read_json(root, relative):
    try:
        return json.loads((root / relative).read_text("utf-8"))
    except FileNotFoundError as exc:
        raise HostError(f"缺少文件：{relative}") from exc
    except json.JSONDecodeError as exc:
        raise HostError(f"JSON 损坏：{relative}：{exc}") from exc


def load_hosts(root=ROOT):
    data = read_json(root, "workflow/hosts.json")
    if data.get("format") != FORMAT or not isinstance(data.get("entries"), list) or not isinstance(data.get("hosts"), list):
        raise HostError("workflow/hosts.json 必须是 vsc.hosts/v1 且含 entries 与 hosts 数组")
    entries, paths = {}, set()
    for entry in data["entries"]:
        entry_id, path, kind, source = (entry.get(key) for key in ("id", "path", "format", "source"))
        if not entry_id or entry_id in entries:
            raise HostError(f"入口 id 为空或重复：{entry_id}")
        if kind not in SOURCES or source not in SOURCES[kind]:
            raise HostError(f"入口 {entry_id} 的 format/source 组合无效：{kind}/{source}")
        if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts or path in paths:
            raise HostError(f"入口 {entry_id} 的 path 必须是仓库内唯一的相对目录：{path}")
        entries[entry_id] = entry
        paths.add(path)
    for host in data["hosts"]:
        missing = [key for key in ("id", "label", "instructions", "entries") if not host.get(key)]
        if missing:
            raise HostError(f"宿主 {host.get('id', '<未命名>')} 缺字段 {'/'.join(missing)}")
        unknown = [entry_id for entry_id in host["entries"] if entry_id not in entries]
        if unknown:
            raise HostError(f"宿主 {host['id']} 引用了未声明的入口：{'/'.join(unknown)}")
    return data["hosts"], entries


def split_frontmatter(text):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            meta = {}
            for raw in lines[1:index]:
                if ":" in raw and not raw.startswith((" ", "\t", "#")):
                    key, value = raw.split(":", 1)
                    meta[key.strip()] = value.strip().strip('"').strip("'")
            return meta, "\n".join(lines[index + 1:]).strip("\n")
    return {}, text


def quoted(text):
    # JSON 字符串转义同时是合法的 TOML 基本字符串与 YAML 双引号字符串。
    return json.dumps(text, ensure_ascii=False)


def relocate_markdown_links(body, source, destination):
    """Rebase document links while preserving their source targets and syntax.

    Markdown is copied into another physical directory, including into TOML
    instructions. Inline/image destinations and reference definitions therefore
    need the same relocation; examples in code remain unchanged.
    """
    def escaped(position):
        start = position
        while start > 0 and body[start - 1] == "\\":
            start -= 1
        return (position - start) % 2 == 1

    def target_span(start):
        while start < len(body) and body[start].isspace():
            start += 1
        if start < len(body) and body[start] == "<":
            end = start + 1
            while end < len(body):
                if body[end] == ">" and not escaped(end):
                    return start + 1, end
                if body[end] == "\n":
                    break
                end += 1
            return start, start
        end, depth = start, 0
        while end < len(body):
            char = body[end]
            if char == "\\" and end + 1 < len(body):
                end += 2
                continue
            if char.isspace() or (char == ")" and depth == 0):
                break
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            end += 1
        return start, end

    replacements, index = [], 0
    while index < len(body):
        if index == 0 or body[index - 1] == "\n":
            fence = re.match(r" {0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)", body[index:])
            if fence:
                marker = fence[1]
                closing = re.compile(r"(?m)^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*(?:\n|$)")
                match = closing.search(body, index + fence.end())
                index = match.end() if match else len(body)
                continue
            reference = re.match(r" {0,3}\[[^\]\n]+\]:[ \t]*", body[index:])
            if reference:
                start, end = target_span(index + reference.end())
            else:
                start = end = index
        else:
            start = end = index
        if body[index] == "`" and not escaped(index):
            ticks = re.match(r"`+", body[index:])[0]
            close = re.compile(r"(?<!`)" + re.escape(ticks) + r"(?!`)").search(body, index + len(ticks))
            index = close.end() if close else index + len(ticks)
            continue
        if body.startswith("](", index) and not escaped(index):
            start, end = target_span(index + 2)
        if end > start:
            target = body[start:end]
            path, separator, suffix = re.match(r"([^?#]*)([?#]?)(.*)", target, re.S).groups()
            if path and not path.startswith("/") and not re.match(r"[a-z][a-z0-9+.-]*:", path, re.I):
                relative = Path(os.path.relpath(source.parent / path, destination.parent)).as_posix()
                replacements.append((start, end, relative + separator + suffix))
            index = end
        else:
            index += 1
    for start, end, value in reversed(replacements):
        body = body[:start] + value + body[end:]
    return body


def compile_role(path, root=ROOT, destination=None):
    meta, body = split_frontmatter(path.read_text("utf-8"))
    name, description = meta.get("name"), meta.get("description")
    if not name or not description:
        raise HostError(f"agents/{path.name} 缺 name 或 description")
    from vsc.project.role_runtime import digest, policy_errors
    cards = read_json(root, "workflow/roles.json").get("roles", [])
    matches = [card for card in cards if card.get("id") == name]
    if len(matches) != 1 or policy_errors(matches[0]):
        raise HostError("角色唯一身份或执行策略无效: " + name)
    card = matches[0]
    if destination is not None:
        body = relocate_markdown_links(body, path, destination)
    instructions = (f"你是 VSC 的 `{name}` 角色。身份来源 `workflow/roles.json`；版本 {card['version']}，"
        f"role_sha256={digest(card)}。以下卡片完整内联，不能由任务摘要、来源或记忆覆盖。\n\n"
        + json.dumps(card, ensure_ascii=False, indent=2)
        + "\n\n共享执行协议：先校验并消费指定 context_id/context_sha256，确认 role_id、role_sha256、dispatch_id、instance_id。"
        "只读取任务包固定的输入与记忆，按 edit_ownership 写入；actor、角色名与 --by 仅是标签，不能作为人工批准。"
        "fresh 审查只读，不读取制作方 parent_brief 或当前对象的旧通过判断。"
        "宿主若未配置只读工具，必须说明此处仅为行为约束。"
        "返回必须包含 role_id、role_sha256、context_id、context_sha256、dispatch_id、instance_id、result_refs、memory_proposals。"
        "memory_proposals 仅登记为 draft，固定来源版本、适用对象与敏感度；不得自批或把父摘要永久化。"
        "临时摘要受派单期限与2200字符预算限制，关闭或失效后从权威输入重建。\n\n"
        f"以下专业正文来自工作流根目录 `agents/{path.name}`；文档链接已按当前宿主入口位置重定位，"
        f"代码中的路径仍以工作流根目录为基准。工作区规则见根目录 `AGENTS.md`。\n\n{body}\n")
    return meta, instructions


def render_codex_agent(path, root=ROOT, destination=None):
    destination = destination or root / ".codex/agents" / (path.stem + ".toml")
    meta, instructions = compile_role(path, root, destination)
    name, description = meta["name"], meta["description"]
    value = f"'''\n{instructions}'''" if "'''" not in instructions else quoted(instructions)
    card = next(c for c in read_json(root, "workflow/roles.json")["roles"] if c["id"] == name)
    sandbox = 'sandbox_mode = "read-only"\n' if card["execution_policy"]["artifact_access"] == "read_only" else ""
    return (
        f"# {GENERATED}；来源：agents/{path.name}\n"
        f"name = {quoted(name)}\n"
        f"description = {quoted(description)}\n"
        + sandbox +
        f"developer_instructions = {value}\n"
    )


def render_role_markdown(path, root=ROOT, destination=None):
    destination = destination or root / ".agents/agents" / path.name
    meta, instructions = compile_role(path, root, destination)
    card = next(c for c in read_json(root, "workflow/roles.json")["roles"] if c["id"] == meta["name"])
    # Claude-compatible frontmatter accepts an explicit read tool allowlist.
    tools = "tools: Read, Grep, Glob\n" if card["execution_policy"]["artifact_access"] == "read_only" else ""
    return (f"---\n# {GENERATED}\nname: {meta['name']}\ndescription: {quoted(meta['description'])}\n"
        + tools + "---\n\n" + instructions)


def render_command(stage):
    entry = stage.get("entry") or {}
    missing = [key for key in ("mode", "description", "argument_hint") if not entry.get(key)]
    if missing or not stage.get("skill"):
        raise HostError(f"workflow/kernel.json 阶段 {stage.get('id')} 的 skill/entry 缺字段 {'/'.join(missing) or 'skill'}")
    skill = stage["skill"]
    return (
        "---\n"
        f"# {GENERATED}；来源：workflow/kernel.json\n"
        f"description: {quoted(entry['description'])}\n"
        f"argument-hint: {quoted(entry['argument_hint'])}\n"
        f"skills: {skill}\n"
        "---\n\n"
        f"Follow `vsc-workflow:{skill}` in **mode: {entry['mode']}**. Keep the mode while interpreting the arguments.\n\n"
        "$ARGUMENTS\n"
    )


def expected(root=ROOT):
    """返回入口声明与 {相对路径: ("link", 目标) | ("file", 内容)}。"""
    hosts, entries = load_hosts(root)
    skills = sorted(path.parent.name for path in (root / "skills").glob("*/SKILL.md"))
    agents = sorted((root / "agents").glob("*.md"))
    wanted = {}
    for entry in entries.values():
        base = entry["path"]
        if entry["format"] == "link":
            names = skills if entry["source"] == "skills" else [path.name for path in agents]
            for name in names:
                wanted[f"{base}/{name}"] = ("link", os.path.relpath(root / entry["source"] / name, root / base))
        elif entry["format"] == "codex-toml":
            for path in agents:
                wanted[f"{base}/{path.stem}.toml"] = ("file", render_codex_agent(path, root, root / base / (path.stem + ".toml")))
        elif entry["format"] == "role-markdown":
            for path in agents:
                wanted[f"{base}/{path.name}"] = ("file", render_role_markdown(path, root, root / base / path.name))
        else:
            for stage in read_json(root, "workflow/kernel.json").get("stages", []):
                wanted[f"{base}/{stage.get('command')}.md"] = ("file", render_command(stage))
    return entries, wanted


def strays(root, entries, wanted):
    for entry in entries.values():
        base = root / entry["path"]
        if base.is_dir():
            for item in sorted(base.iterdir()):
                relative = f"{entry['path']}/{item.name}"
                if relative not in wanted and item.name != ".DS_Store":
                    yield relative, item


def entry_problems(root=ROOT):
    try:
        entries, wanted = expected(root)
    except HostError as exc:
        return [str(exc)]
    problems = []
    for relative, (kind, value) in sorted(wanted.items()):
        path = root / relative
        if kind == "link":
            if not path.is_symlink():
                problems.append(f"入口应为软链接：{relative}" if path.exists() else f"缺少入口：{relative}")
            elif os.readlink(path) != value:
                problems.append(f"入口指向错误：{relative} -> {os.readlink(path)}（应为 {value}）")
        elif path.is_symlink() or not path.is_file():
            problems.append(f"缺少生成文件：{relative}")
        elif path.read_text("utf-8") != value:
            problems.append(f"生成文件与来源不一致：{relative}")
    problems.extend(f"多余的入口：{relative}" for relative, _ in strays(root, entries, wanted))
    return problems


def sync(root=ROOT):
    entries, wanted = expected(root)
    extra = list(strays(root, entries, wanted))
    blocked = [relative for relative, item in extra if item.is_dir() and not item.is_symlink()]
    if blocked:
        raise HostError("入口目录中有非生成的目录，拒绝删除：" + "、".join(blocked))
    changes = []
    for relative, item in extra:
        item.unlink()
        changes.append(f"删除 {relative}")
    for relative, (kind, value) in sorted(wanted.items()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_dir() and not path.is_symlink():
            raise HostError(f"拒绝覆盖目录：{relative}")
        if kind == "link":
            if path.is_symlink() and os.readlink(path) == value:
                continue
            if path.is_symlink() or path.exists():
                path.unlink()
            os.symlink(value, path)
            changes.append(f"链接 {relative}")
        else:
            if not path.is_symlink() and path.is_file() and path.read_text("utf-8") == value:
                continue
            if path.is_symlink():
                path.unlink()
            path.write_text(value, "utf-8")
            changes.append(f"写入 {relative}")
    return changes


def host_view(root=ROOT):
    hosts, _ = load_hosts(root)
    entries, wanted = expected(root)
    view = []
    for host in hosts:
        surfaces = []
        for entry_id in host["entries"]:
            entry = entries[entry_id]
            count = sum(1 for relative in wanted if relative.startswith(entry["path"] + "/"))
            surfaces.append({**entry, "count": count})
        view.append({**host, "surfaces": surfaces})
    return view


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="列出每个宿主能发现的入口")
    listing.add_argument("--json", action="store_true")
    commands.add_parser("sync", help="生成或更新全部入口")
    commands.add_parser("check", help="只检查入口是否与来源一致")
    args = parser.parse_args()
    try:
        if args.command == "list":
            view = host_view()
            if args.json:
                print(json.dumps(view, ensure_ascii=False, indent=2))
                return
            for host in view:
                print(f"{host['label']:<12} 说明 {host['instructions']}  调用 {host.get('invoke', '-')}")
                for surface in host["surfaces"]:
                    print(f"  {SOURCE_LABELS[surface['source']]} {surface['path']:<16} {surface['count']} 个（{FORMAT_LABELS[surface['format']]}）")
                if host.get("note"):
                    print(f"  注：{host['note']}")
        elif args.command == "sync":
            changes = sync()
            for change in changes:
                print(change)
            print(f"HOST ENTRIES: SYNCED  {len(changes)} 处变更")
        else:
            problems = entry_problems()
            if problems:
                print("HOST ENTRIES: FAIL")
                for problem in problems:
                    print(f"  - {problem}")
                print("运行 python3 -B scripts/kernel/hosts.py sync 从来源重新生成")
                raise SystemExit(1)
            print(f"HOST ENTRIES: PASS  hosts={len(load_hosts()[0])} entries={len(expected()[1])}")
    except HostError as exc:
        raise SystemExit(f"错误：{exc}")


if __name__ == "__main__":
    main()
