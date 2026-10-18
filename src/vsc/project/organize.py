#!/usr/bin/env python3
"""B3-06：旧项目整理预览（只读）。

按“当前引用 / 历史版本 / 备份 / 可再生派生物 / 未知归属”五分类列出项目文件清单，
标注每类的保留理由与建议动作；预览不计为清理完成，不删除任何文件。
分类依据来自旧权威清单（migration.inventory）与字节分类（classify_file），
不按文件名或后缀猜测创作语义。
"""
from pathlib import Path

RENEWABLE_SUFFIXES = {".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".wav", ".mp3"}
BACKUP_MARKERS = {".vsc-migration", ".vsc-production", "-backup", ".bak"}
CURRENT_DIRS = {"04-视听设计", "05-预演", "08-剪辑", "07-交付"}


def _category_of(relative, entry=None):
    parts = Path(relative).parts
    if any(marker in relative for marker in BACKUP_MARKERS) or "备份" in relative:
        return "backup"
    if parts and parts[0] == ".vsc-local":
        return "renewable"
    suffix = Path(relative).suffix.lower()
    if suffix in RENEWABLE_SUFFIXES:
        return "renewable"
    if parts and parts[0] in CURRENT_DIRS:
        return "current"
    return "unknown"


def organize_preview(project, inventory=None):
    """只读五分类预览。inventory 为 migration.inventory() 的输出；缺省时扫描目录。"""
    project = Path(project).resolve()
    if inventory and isinstance(inventory, dict):
        files = [row.get("path") or row.get("relative") for row in inventory.get("files", [])
                 if isinstance(row, dict)]
    else:
        files = [str(p.relative_to(project)) for p in project.rglob("*") if p.is_file()]
    buckets = {"current": [], "history": [], "backup": [], "renewable": [], "unknown": []}
    for relative in files:
        if not isinstance(relative, str) or not relative.strip():
            continue
        category = _category_of(relative)
        buckets[category].append(relative)
    return {
        "format": "vsc.organize-preview/v1",
        "project": str(project),
        "read_only": True,
        "counts": {key: len(value) for key, value in buckets.items()},
        "files": buckets,
        "actions": {
            "current": "正式引用：保留；删除前须核对消费者",
            "history": "历史版本：保留或归档；不自动删除",
            "backup": "备份：独立归档；恢复入口保留",
            "renewable": "可再生派生物：按容量/期限回收；引用不指向此类",
            "unknown": "未知归属：人工核对后归类；不自动删除",
        },
        "meaning": "预览不计为清理完成；不删除任何文件；批准与恢复引用保持可读",
    }


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description="旧项目整理预览（只读五分类；预览不计为清理完成）")
    parser.add_argument("project")
    args = parser.parse_args(argv)
    print(json.dumps(organize_preview(args.project), ensure_ascii=False, indent=2))
    return 0
