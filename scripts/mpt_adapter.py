#!/usr/bin/env python3
"""VSC × MoneyPrinterTurbo 适配器：调用本机固定版本的 MoneyPrinterTurbo CLI。

  prepare                                    把字体与音乐链接进 MoneyPrinterTurbo 的 resource 目录
  voice PROJECT --lines LINES.json [--voice V] [--rate R] [--artifact A-ID]
                                             为已批准剧本的台词生成预演临时配音与逐词字幕

prepare 总是链接 OFL 授权的 noto-sans-sc；只有用户显式安装了 moneyprinterturbo-assets，才同时链接其附带的
商业字体与无授权说明的 BGM，并提示商用前须取得授权。

voice 的 LINES.json 是数组：[{"id": "DX-01", "text": "台词", "voice": "可选", "rate": 可选}]。每条台词单独生成，
写入 PROJECT/05-预演/临时配音/<运行时间>/：<id>.mp3、<id>.srt 与 生成记录.json。临时配音只用于预演：Edge-TTS
调用微软在线朗读服务，声音的商业使用授权未经核验，不得进入交付物。本脚本不调用大模型，不生成画面、BGM 或成片，
也不登记或批准产物。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from vendor_sync import VENDOR, installed_problem, locked_source

ROOT = Path(__file__).resolve().parent.parent
MPT_ID = "moneyprinterturbo"
ASSETS_ID = "moneyprinterturbo-assets"
FONT_ID = "noto-sans-sc"
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural-Female"
DEFAULT_FONT = "NotoSansSC-Bold.otf"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
TEMP_USE = "仅限预演临时音轨，不得进入交付物：Edge-TTS 调用微软在线朗读服务，声音的商业使用授权未经核验。"
ASSET_NOTICE = "微软雅黑、华文黑体等商业字体与无授权说明的 BGM 仅供本机评估；用于商业作品或对外发布前，须向版权方取得商用授权。"


class AdapterError(RuntimeError):
    """上游未就绪或输入无效。"""


def require_installed(source_id, vendor_root=VENDOR):
    problem = installed_problem(locked_source(source_id), vendor_root)
    if problem:
        raise AdapterError(problem)
    return vendor_root / source_id


def resource_links(vendor_root=VENDOR):
    """返回 {resource 下的相对路径: 目标文件}。OFL 字体总是链接；附带资源仅在用户安装后链接。"""
    links = {}
    fonts = vendor_root / FONT_ID / "Sans" / "SubsetOTF" / "SC"
    for path in sorted(fonts.glob("*.otf")):
        links[f"fonts/{path.name}"] = path
    # 附带资源加 assets- 前缀：避开上游已跟踪但未检出的同名文件，也让需要商用授权的资源一眼可辨。
    assets = vendor_root / ASSETS_ID / "resource"
    for kind in ("fonts", "songs"):
        for path in sorted((assets / kind).glob("*")):
            if path.is_file():
                links[f"{kind}/assets-{path.name}"] = path
    return links


def ensure_config(mpt):
    """上游未设字幕字体时回落到华文黑体；VSC 的本机配置默认改用 OFL 字体，并关闭完成后弹出文件夹。"""
    config = mpt / "config.toml"
    created = not config.exists()
    if created:
        shutil.copyfile(mpt / "config.example.toml", config)
    text = config.read_text("utf-8")
    if created:
        text = text.replace("open_task_folder_on_completion = true", "open_task_folder_on_completion = false")
    if not re.search(r"(?m)^font_name\s*=", text) and re.search(r"(?m)^\[ui\]\s*$", text):
        text = re.sub(r"(?m)^\[ui\]\s*$", f'[ui]\nfont_name = "{DEFAULT_FONT}"', text, count=1)
    config.write_text(text, "utf-8")
    return config


def prepare(vendor_root=VENDOR):
    mpt = require_installed(MPT_ID, vendor_root)
    require_installed(FONT_ID, vendor_root)
    ensure_config(mpt)
    resource = mpt / "resource"
    wanted = resource_links(vendor_root)
    for kind in ("fonts", "songs"):
        directory = resource / kind
        directory.mkdir(parents=True, exist_ok=True)
        # 只清理本适配器建立的软链接；上游或用户放入的真实文件不动。
        for item in directory.iterdir():
            if item.is_symlink() and f"{kind}/{item.name}" not in wanted:
                item.unlink()
    for relative, target in wanted.items():
        link = resource / relative
        value = os.path.relpath(target, link.parent)
        if link.is_symlink() and os.readlink(link) == value:
            continue
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            continue
        os.symlink(value, link)
    assets_installed = (vendor_root / ASSETS_ID).is_dir()
    return {
        "fonts": sorted(name.split("/", 1)[1] for name in wanted if name.startswith("fonts/")),
        "songs": sum(1 for name in wanted if name.startswith("songs/")),
        "default_font": DEFAULT_FONT,
        "assets_installed": assets_installed,
    }


def load_lines(path):
    try:
        lines = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"无法读取台词文件：{exc}") from exc
    if not isinstance(lines, list) or not lines:
        raise AdapterError("台词文件必须是非空数组")
    seen = set()
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise AdapterError(f"第 {index + 1} 项必须是对象")
        line_id, text = line.get("id"), line.get("text")
        if not isinstance(line_id, str) or not SAFE_ID.fullmatch(line_id) or line_id in seen:
            raise AdapterError(f"第 {index + 1} 项 id 必须唯一，且只含字母、数字、点、下划线和连字符")
        if not isinstance(text, str) or not text.strip():
            raise AdapterError(f"{line_id} 缺少台词 text")
        seen.add(line_id)
    return lines


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def cli_result(stdout):
    """MoneyPrinterTurbo CLI 成功时最后输出一行 JSON：{"task_id": ..., "result": {...}}。"""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and "task_id" in data:
                return data
    raise AdapterError("MoneyPrinterTurbo 没有输出结果 JSON")


def voice_command(uv, mpt, text, voice, rate, task_id):
    return [uv, "run", "--frozen", "--directory", str(mpt), "python", "cli.py",
            "--video-script", text, "--video-terms", "vsc", "--stop-at", "subtitle",
            "--voice-name", voice, "--voice-rate", str(rate), "--task-id", task_id]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def generate_voice(project, lines_path, voice=DEFAULT_VOICE, rate=1.0, artifact=None, vendor_root=VENDOR, run=subprocess.run):
    project = Path(project).resolve()
    if not (project / "vsc.json").is_file():
        raise AdapterError(f"不是 VSC 项目：{project}")
    lines = load_lines(lines_path)
    mpt = require_installed(MPT_ID, vendor_root)
    uv = shutil.which("uv")
    if not uv:
        raise AdapterError("需要 uv：https://docs.astral.sh/uv/")
    ensure_config(mpt)
    started = now()
    output = project / "05-预演" / "临时配音" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    outputs, errors = [], []
    for line in lines:
        line_voice, line_rate = line.get("voice") or voice, line.get("rate") or rate
        task_id = str(uuid.uuid4())
        result = run(voice_command(uv, mpt, line["text"], line_voice, line_rate, task_id),
                     capture_output=True, text=True, timeout=600)
        try:
            if result.returncode:
                raise AdapterError(f"exit {result.returncode}：{(result.stderr or result.stdout).strip()[-300:]}")
            subtitle = Path(cli_result(result.stdout)["result"]["subtitle_path"])
            audio = subtitle.parent / "audio.mp3"
            for produced in (audio, subtitle):
                if not produced.is_file() or produced.stat().st_size == 0:
                    raise AdapterError(f"缺少输出：{produced.name}")
        except (AdapterError, KeyError, TypeError) as exc:
            errors.append({"id": line["id"], "error": str(exc)})
            continue
        audio_out, subtitle_out = output / f"{line['id']}.mp3", output / f"{line['id']}.srt"
        shutil.copyfile(audio, audio_out)
        shutil.copyfile(subtitle, subtitle_out)
        outputs.append({
            "id": line["id"], "text": line["text"], "voice": line_voice, "rate": line_rate, "task_id": task_id,
            "audio": str(audio_out.relative_to(project)), "subtitle": str(subtitle_out.relative_to(project)),
            "sha256": {"audio": sha256(audio_out), "subtitle": sha256(subtitle_out)},
        })
    record = {
        "kind": "预演临时配音",
        "use": TEMP_USE,
        "adapter": {"source": MPT_ID, "revision": locked_source(MPT_ID)["revision"], "stage": "subtitle", "tts": "edge"},
        "inputs": {"lines": str(Path(lines_path).resolve()), "lines_sha256": sha256(lines_path), "artifact": artifact},
        "budget": {"provider": "edge-tts", "billable": False},
        "started_at": started,
        "finished_at": now(),
        "outputs": outputs,
        "errors": errors,
        "selection": None,
    }
    (output / "生成记录.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return output, record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="链接字体与音乐资源")
    voice = commands.add_parser("voice", help="生成预演临时配音与逐词字幕")
    voice.add_argument("project")
    voice.add_argument("--lines", required=True, help="台词 JSON 数组")
    voice.add_argument("--voice", default=DEFAULT_VOICE, help=f"默认音色（默认 {DEFAULT_VOICE}）")
    voice.add_argument("--rate", type=float, default=1.0, help="语速倍率（默认 1.0）")
    voice.add_argument("--artifact", help="台词所依据的已批准剧本产物 ID")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            summary = prepare()
            print(f"MPT RESOURCES: 字体 {len(summary['fonts'])} 款，BGM {summary['songs']} 首；VSC 默认字体 {summary['default_font']}（OFL）")
            if summary["assets_installed"]:
                print("注意：" + ASSET_NOTICE)
            return
        output, record = generate_voice(args.project, args.lines, args.voice, args.rate, args.artifact)
        print(f"TEMP VOICE: {len(record['outputs'])} 条完成，{len(record['errors'])} 条失败 → {output}")
        print("注意：" + TEMP_USE)
        for error in record["errors"]:
            print(f"  - {error['id']}：{error['error']}")
        if record["errors"]:
            raise SystemExit(1)
    except AdapterError as exc:
        raise SystemExit(f"错误：{exc}")


if __name__ == "__main__":
    main()
