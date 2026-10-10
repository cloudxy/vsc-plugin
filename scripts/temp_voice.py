#!/usr/bin/env python3
"""VSC 预演临时配音：为已批准剧本的台词生成配音与字幕。

  generate PROJECT --lines LINES.json [--voice V] [--rate R] [--word-level] [--artifact A-ID]

LINES.json 是数组：[{"id": "DX-01", "text": "台词", "voice": "可选", "rate": 可选}]。每条台词单独生成，写入
PROJECT/05-预演/临时配音/<运行时间>/：<id>.mp3、<id>.srt 与 生成记录.json。字幕默认按剧本标点聚合成整句，
--word-level 输出逐词字幕；整句对不上时自动退回逐词。

声音来自 edge-tts（LGPL-3.0 库，调用微软在线朗读服务）。它由 uv 在独立进程中按 EDGE_TTS 固定的版本运行，
VSC 自身代码只用标准库。本脚本不调用大模型，不生成画面、BGM 或成片，不登记或批准产物。
"""
import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import subtitles

EDGE_TTS = "edge-tts==7.2.7"
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
TEMP_USE = "仅限预演临时音轨，不得进入交付物：声音来自微软在线朗读服务，商业使用授权未经核验。"


class VoiceError(RuntimeError):
    """输入无效或运行环境未就绪。"""


def load_lines(path):
    try:
        lines = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceError(f"无法读取台词文件：{exc}") from exc
    if not isinstance(lines, list) or not lines:
        raise VoiceError("台词文件必须是非空数组")
    seen = set()
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise VoiceError(f"第 {index + 1} 项必须是对象")
        line_id, text = line.get("id"), line.get("text")
        if not isinstance(line_id, str) or not SAFE_ID.fullmatch(line_id) or line_id in seen:
            raise VoiceError(f"第 {index + 1} 项 id 必须唯一，且只含字母、数字、点、下划线和连字符")
        if not isinstance(text, str) or not text.strip():
            raise VoiceError(f"{line_id} 缺少台词 text")
        seen.add(line_id)
    return lines


def edge_voice(name):
    """兼容 MoneyPrinterTurbo 风格的 zh-CN-YunxiNeural-Male：edge-tts 只认去掉性别后缀的名字。"""
    return re.sub(r"-(Male|Female)$", "", name.strip())


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def worker(job_path):
    """在带 edge-tts 的 uv 环境中运行：逐条合成音频并记录逐词时间，结果写回作业文件。"""
    import edge_tts

    job = json.loads(Path(job_path).read_text("utf-8"))
    for item in job["lines"]:
        item["cues"], item["error"] = [], None
        for _ in range(3):
            cues = []
            try:
                communicate = edge_tts.Communicate(item["text"], item["voice"], rate=item["rate"], boundary="WordBoundary")
                with open(item["audio"], "wb") as audio:
                    for chunk in communicate.stream_sync():
                        if chunk["type"] == "audio":
                            audio.write(chunk["data"])
                        elif chunk["type"] == "WordBoundary":
                            begin = chunk["offset"] / 10_000_000
                            cues.append((begin, begin + chunk["duration"] / 10_000_000, chunk["text"]))
                if Path(item["audio"]).stat().st_size and cues:
                    item["cues"], item["error"] = cues, None
                    break
                item["error"] = "edge-tts 没有返回音频或逐词时间"
            except Exception as exc:  # 网络与服务端错误都按重试处理，最终如实记录
                item["error"] = f"{type(exc).__name__}: {exc}"
    Path(job_path).write_text(json.dumps(job, ensure_ascii=False), "utf-8")


def synthesize(job_path, run=subprocess.run):
    uv = shutil.which("uv")
    if not uv:
        raise VoiceError("需要 uv：https://docs.astral.sh/uv/")
    result = run([uv, "run", "--no-project", "--python", "3.12", "--with", EDGE_TTS, "python", str(Path(__file__).resolve()), "worker", str(job_path)],
                 capture_output=True, text=True, timeout=1800)
    if result.returncode:
        raise VoiceError(f"edge-tts 进程失败（exit {result.returncode}）：{(result.stderr or result.stdout).strip()[-500:]}")


def generate(project, lines_path, voice=DEFAULT_VOICE, rate=1.0, word_level=False, artifact=None, run=subprocess.run):
    project = Path(project).resolve()
    if not (project / "vsc.json").is_file():
        raise VoiceError(f"不是 VSC 项目：{project}")
    lines = load_lines(lines_path)
    output = project / "05-预演" / "临时配音" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    started = now()
    job = {"lines": [{"id": line["id"], "text": line["text"], "voice": edge_voice(line.get("voice") or voice),
                      "rate": subtitles.rate_to_percent(line.get("rate") or rate), "audio": str(output / f"{line['id']}.mp3")}
                     for line in lines]}
    with tempfile.TemporaryDirectory() as temp:
        job_path = Path(temp) / "job.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False), "utf-8")
        synthesize(job_path, run)
        job = json.loads(job_path.read_text("utf-8"))
    outputs, errors = [], []
    for item in job["lines"]:
        if item.get("error") or not item.get("cues"):
            errors.append({"id": item["id"], "error": item.get("error") or "没有结果"})
            Path(item["audio"]).unlink(missing_ok=True)
            continue
        cues = [tuple(cue) for cue in item["cues"]]
        grouped = None if word_level else subtitles.group_word_cues(cues, item["text"])
        subtitle = output / f"{item['id']}.srt"
        subtitle.write_text(subtitles.to_srt(grouped or cues), "utf-8")
        outputs.append({
            "id": item["id"], "text": item["text"], "voice": item["voice"], "rate": item["rate"],
            "subtitle_mode": "sentence" if grouped else "word",
            "audio": str(Path(item["audio"]).relative_to(project)), "subtitle": str(subtitle.relative_to(project)),
            "duration_seconds": round(cues[-1][1], 3),
            "sha256": {"audio": sha256(item["audio"]), "subtitle": sha256(subtitle)},
        })
    record = {
        "kind": "预演临时配音",
        "use": TEMP_USE,
        "engine": EDGE_TTS,
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
    if len(sys.argv) == 3 and sys.argv[1] == "worker":
        worker(sys.argv[2])
        return
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("generate", help="生成预演临时配音与字幕")
    command.add_argument("project")
    command.add_argument("--lines", required=True, help="台词 JSON 数组")
    command.add_argument("--voice", default=DEFAULT_VOICE, help=f"默认音色（默认 {DEFAULT_VOICE}）")
    command.add_argument("--rate", type=float, default=1.0, help="语速倍率（默认 1.0）")
    command.add_argument("--word-level", action="store_true", help="输出逐词字幕")
    command.add_argument("--artifact", help="台词所依据的已批准剧本产物 ID")
    args = parser.parse_args()
    try:
        output, record = generate(args.project, args.lines, args.voice, args.rate, args.word_level, args.artifact)
    except VoiceError as exc:
        raise SystemExit(f"错误：{exc}")
    print(f"TEMP VOICE: {len(record['outputs'])} 条完成，{len(record['errors'])} 条失败 → {output}")
    print("注意：" + TEMP_USE)
    for error in record["errors"]:
        print(f"  - {error['id']}：{error['error']}")
    if record["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
