#!/usr/bin/env python3
"""生成原创程序化声音候选，无外部采样、无联网：环境底、拟音与简约配乐。

这不是豆包模型。固定 seed 与参数可复现；声音仍需试听、选择及混音。
"""
import argparse
import array
import json
import math
import random
import sys
import tempfile
import wave
from pathlib import Path

import consistency as C
import volc_ark as A

PROVIDER = "vsc_procedural_audio"
PRESETS = {
    "wind": ("ambience", "柔和风声", "低频随机气流，无人声；循环使用建议交叠100ms"),
    "rain": ("ambience", "细雨底声", "宽带细雨与稀疏水滴，无人声；循环使用建议交叠100ms"),
    "cloth": ("sfx", "衣物摩擦", "短促噪声脉冲，供动作接点拟音"),
    "footsteps": ("sfx", "缓慢脚步", "每0.65秒交替的低频落步与鞋底摩擦"),
    "ceramic": ("sfx", "陶瓷轻碰", "带衰减的非整数倍泛音，不含外部器物采样"),
    "bell": ("sfx", "远处钟音", "缓慢衰减的多泛音钟音"),
    "music_pad": ("music", "简约悬浮配乐", "原创A小调分解和声，无旋律采样、无人声；对白下须另行避让"),
}
RATE = 24000


def synthesize(preset, duration, seed=0, level_db=-20):
    if preset not in PRESETS or not math.isfinite(duration) or not 0.05 <= duration <= 120:
        raise ValueError("preset 无效或时长不在0.05–120秒之间")
    if not math.isfinite(level_db) or not -60 <= level_db <= -6:
        raise ValueError("level_db 必须在-60到-6 dBFS之间")
    rng, smooth, values = random.Random(seed), 0.0, []
    count = round(duration * RATE)
    for i in range(count):
        t = i / RATE
        white = rng.uniform(-1, 1)
        smooth = 0.985 * smooth + 0.015 * white
        if preset == "wind":
            v = smooth * 5 * (0.6 + 0.2 * math.sin(t * 1.3) + 0.1 * math.sin(t * 3.1))
        elif preset == "rain":
            v = 0.32 * white + 0.12 * math.sin(2 * math.pi * 1800 * t) * math.exp(-((t % 0.37) * 180))
        elif preset in ("cloth", "footsteps"):
            phase = t % (0.65 if preset == "footsteps" else 0.8)
            attack = (1 - math.exp(-phase * 500)) * math.exp(-phase * 28)
            v = attack * (0.6 * math.sin(2 * math.pi * 90 * phase) + 0.25 * white) if preset == "footsteps" else attack * (white - smooth)
        elif preset in ("ceramic", "bell"):
            freq, decay = (980, 5.0) if preset == "ceramic" else (220, 0.7)
            v = sum(math.sin(2 * math.pi * freq * ratio * t) * math.exp(-t * decay * (1 + k * 0.4)) / (k + 1)
                    for k, ratio in enumerate((1, 2.07, 2.81, 4.13)))
            v *= min(t * 250, 1)
        else:
            # 自编四和弦，分层交叠；没有引用已有曲目或录音。
            chords = ((220, 261.626, 329.628), (174.614, 220, 261.626),
                      (130.813, 164.814, 195.998), (195.998, 246.942, 293.665))
            v = 0.0
            for index, chord in enumerate(chords):
                phase = (t - index * 3) % 12
                envelope = min(phase / 0.6, 1) * max(0, min((3.6 - phase) / 0.6, 1))
                v += envelope * sum(math.sin(2 * math.pi * f * t) / 3 for f in chord)
        fade = min(1, i / max(1, RATE * 0.02), (count - 1 - i) / max(1, RATE * 0.05))
        values.append(v * fade)
    peak = max(abs(x) for x in values)
    gain = 10 ** (level_db / 20) / peak if peak else 0
    result = array.array("h", (round(x * gain * 32767) for x in values))
    return result


def write_wave(path, samples):
    if sys.byteorder != "little":
        samples = array.array("h", samples)
        samples.byteswap()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(samples.tobytes())


def generate(args):
    args.project = str(Path(args.project).resolve())
    # 参数和全部路径先检查；本机重算不产生远程费用。
    if not math.isfinite(args.duration) or not 0.05 <= args.duration <= 120 or not math.isfinite(args.level_db) or not -60 <= args.level_db <= -6:
        raise ValueError("时长须在0.05–120秒，峰值须在-60到-6 dBFS")
    out = A.output_dir(args)
    target = A.project_path(args.project, str((out / (args.name + ".wav")).relative_to(args.project)))
    record_path = out / f"{args.name}-生成记录.json"
    task_path = out / f"{args.name}-本地任务.json"
    for path in (target, record_path, task_path):
        if path.is_symlink():
            raise ValueError("音频或记录不能是符号链接")
    binding = {"project_id": A.project_id(args.project), "preset": args.preset, "duration": args.duration,
               "seed": args.seed, "level_db": args.level_db, "sample_rate": RATE, "version": 1}
    with A.generation_lock(out, args.name):
        if task_path.exists():
            task = json.loads(task_path.read_text("utf-8"))
            if task.get("binding") != binding:
                raise ValueError("同名音频的参数已改变，请使用新name")
            if record_path.exists():
                record = C.load(record_path, C.RECORD_FORMAT)
                expected_inputs = {"prompt": PRESETS[args.preset][2], "references": []}
                expected_engine = {"provider": PROVIDER, "model": "original-synthesis-v1", "params": binding}
                if (C.record_errors(record) or record.get("project_id") != binding["project_id"]
                        or record.get("kind") != "audio" or record.get("purpose") != "asset"
                        or record.get("shot_id") is not None or record.get("errors")
                        or record.get("inputs") != expected_inputs or record.get("engine") != expected_engine
                        or record.get("budget") != {"billable": False}):
                    raise ValueError("已存在记录与原始任务不符")
                if record["status"] == "succeeded":
                    expected_output = {"id": args.name, "path": str(target.relative_to(args.project)),
                        "sha256": A.sha256(target), "duration_ms": round(round(args.duration * RATE) / RATE * 1000),
                        "asset_kind": PRESETS[args.preset][0]}
                    if record.get("outputs") != [expected_output] or not A.checked_outputs(record, args.project):
                        raise ValueError("已生成音频或目标绑定被改动，拒绝覆盖")
                    try:
                        with wave.open(str(target), "rb") as audio:
                            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes(), audio.getcomptype()) != (1, 2, RATE, round(args.duration * RATE), "NONE"):
                                raise ValueError("已生成 WAV 参数不符")
                            actual = audio.readframes(audio.getnframes())
                        expected = synthesize(args.preset, args.duration, args.seed, args.level_db)
                        if sys.byteorder != "little":
                            expected.byteswap()
                        if actual != expected.tobytes():
                            raise ValueError("已生成 WAV 样本与原任务不符")
                    except (wave.Error, EOFError) as exc:
                        raise ValueError("已生成音频不是有效 WAV") from exc
                    return record_path
        elif target.exists() or record_path.exists():
            raise ValueError("同名文件已存在而没有可核实任务，拒绝覆盖")
        A.write_json(task_path, {"format": "vsc.procedural-audio-task/v1", "binding": binding})
        samples = synthesize(args.preset, args.duration, args.seed, args.level_db)
        with tempfile.NamedTemporaryFile(suffix=".wav", dir=out, delete=False) as handle:
            temp = Path(handle.name)
        try:
            write_wave(temp, samples)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        record = {"format": C.RECORD_FORMAT, "project_id": binding["project_id"], "kind": "audio", "purpose": "asset", "shot_id": None,
                  "inputs": {"prompt": PRESETS[args.preset][2], "references": []},
                  "engine": {"provider": PROVIDER, "model": "original-synthesis-v1", "params": binding},
                  "budget": {"billable": False}, "submitted_at": A.stamp(A.now()), "finished_at": A.stamp(A.now()),
                  "status": "succeeded", "errors": [], "selection": None,
                  "outputs": [{"id": args.name, "path": str(target.relative_to(args.project)), "sha256": A.sha256(target),
                               "duration_ms": round(len(samples) / RATE * 1000), "asset_kind": PRESETS[args.preset][0]}]}
        return A.write_record(out, args.name, record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", default="06-素材/程序化声音")
    parser.add_argument("--name", required=True)
    parser.add_argument("--preset", choices=PRESETS, required=True)
    parser.add_argument("--duration", type=float, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--level-db", type=float, default=-20)
    args = parser.parse_args(argv)
    try:
        print(generate(args))
    except (ValueError, OSError, A.ArkError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
