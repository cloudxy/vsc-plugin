#!/usr/bin/env python3
"""VSC 派生视图：把声明渲染进文档的标记块，或生成整个派生文件（如 marketplace.json），不再手写第二份。

  sync    重新渲染全部视图
  check   只检查；视图与声明不一致时退出码为 1（doctor 也会检查）

标记块形如 <!-- vsc:view NAME --> … <!-- /vsc:view -->，块内内容由本脚本生成，勿手改。
"""
import argparse
import json
import re
from pathlib import Path

from vsc_hosts import FORMAT_LABELS, SOURCE_LABELS, HostError, host_view

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"(<!-- vsc:view (?P<name>[a-z-]+) -->\n)(?P<body>.*?)(<!-- /vsc:view -->)", re.S)


def render_routes(root):
    stages = json.loads((root / "workflow" / "kernel.json").read_text("utf-8"))["stages"]
    lines = ["| 需求 | 命令／技能 | route 参数 | 角色 |", "|---|---|---|---|"]
    for stage in stages:
        lines.append(f"| {stage['entry']['summary']} | `{stage['command']}` | {stage['id']} | {'、'.join(stage['roles'])} |")
    return "\n".join(lines) + "\n"


def render_hosts(root):
    lines = ["| 客户端 | 工作区说明 | 发现入口 | 调用 | 注意 |", "|---|---|---|---|---|"]
    for host in host_view(root):
        surfaces = "；".join(f"{SOURCE_LABELS[item['source']]} `{item['path']}/`（{item['count']} 个，{FORMAT_LABELS[item['format']]}）" for item in host["surfaces"])
        lines.append(f"| {host['label']} | `{host['instructions']}` | {surfaces} | {host.get('invoke', '')} | {host.get('note', '')} |")
    return "\n".join(lines) + "\n"


def render_version(root):
    version = json.loads((root / ".zcode-plugin" / "plugin.json").read_text("utf-8"))["version"]
    return f"当前版本：**v{version}**，各版本变化见 [版本记录](docs/releases/)。\n"


def render_marketplace(root):
    """ZCode 本地插件市场清单：名称、版本、简介与标签都取自 .zcode-plugin/plugin.json。"""
    plugin = json.loads((root / ".zcode-plugin" / "plugin.json").read_text("utf-8"))
    market = {
        "name": f"{plugin['name']}-market",
        "description": "VSC 短剧与短视频创作工作流的本地 ZCode 插件市场。",
        "plugins": [{
            "name": plugin["name"], "source": "./", "version": plugin["version"],
            "description": plugin["description"].split("。", 1)[0] + "。",
            "category": "creative-production", "tags": plugin["keywords"],
        }],
    }
    return json.dumps(market, ensure_ascii=False, indent=2) + "\n"


# 整个文件都由声明生成的视图。
FILES = {"marketplace.json": render_marketplace}

VIEWS = {
    "version": ("README.md", render_version),
    "routes": ("AGENTS.md", render_routes),
    "hosts": ("docs/guide/workspace-setup.md", render_hosts),
}


def rendered(root=ROOT):
    """返回 {文档相对路径: (现有文本, 应有文本)}。"""
    documents = {}
    for name, (relative, renderer) in VIEWS.items():
        if relative not in documents:
            text = (root / relative).read_text("utf-8")
            documents[relative] = (text, text)
        original, text = documents[relative]
        matches = [match for match in BLOCK.finditer(text) if match.group("name") == name]
        if len(matches) != 1:
            raise HostError(f"{relative} 必须恰好有一个 vsc:view {name} 标记块")
        body = matches[0].span("body")
        documents[relative] = (original, text[:body[0]] + renderer(root) + text[body[1]:])
    for relative, renderer in FILES.items():
        path = root / relative
        documents[relative] = (path.read_text("utf-8") if path.exists() else "", renderer(root))
    return documents


def view_problems(root=ROOT):
    try:
        documents = rendered(root)
    except (HostError, OSError, KeyError, json.JSONDecodeError) as exc:
        return [f"文档视图无法渲染：{exc}"]
    return [f"文档视图已过期：{relative}（运行 python3 -B scripts/vsc_views.py sync）"
            for relative, (current, expected) in documents.items() if current != expected]


def sync(root=ROOT):
    changed = []
    for relative, (current, expected) in rendered(root).items():
        if current != expected:
            (root / relative).write_text(expected, "utf-8")
            changed.append(relative)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("sync", "check"))
    args = parser.parse_args()
    if args.command == "sync":
        for relative in sync():
            print(f"写入 {relative}")
        print("DOC VIEWS: SYNCED")
        return
    problems = view_problems()
    for problem in problems:
        print(f"  - {problem}")
    print("DOC VIEWS: " + ("FAIL" if problems else "PASS"))
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
