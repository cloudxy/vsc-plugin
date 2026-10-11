#!/usr/bin/env python3
"""consistency.py 自测。运行：python3 tests/test_consistency.py"""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT, SCRIPTS
import consistency as C

BIBLE = json.loads((ROOT / "templates/asset-bible.json").read_text("utf-8"))
STATE = json.loads((ROOT / "templates/scene-state.json").read_text("utf-8"))
PLAN = json.loads((ROOT / "templates/continuity-plan.json").read_text("utf-8"))
RECORD = json.loads((ROOT / "templates/generation-record.json").read_text("utf-8"))


def bible(**changes):
    value = copy.deepcopy(BIBLE)
    value.update(changes)
    return value


def state():
    return copy.deepcopy(STATE)


class BibleTest(unittest.TestCase):
    def test_template_is_valid(self):
        self.assertEqual(C.bible_errors(BIBLE), [])

    def test_identity_variants_and_bindings_are_required(self):
        value = bible()
        value["entities"][0]["identity"] = []
        value["entities"][1]["variants"] = {"夜": "冷光"}
        value["entities"][2]["voice"] = {"engine": "edge-tts", "voice": "x", "rights": "temp_only"}
        value["entities"][0]["references"][0]["sha256"] = "abc"
        errors = C.bible_errors(value)
        self.assertTrue(any("identity 不能为空" in error for error in errors))
        self.assertTrue(any("包含 default" in error for error in errors))
        self.assertTrue(any("voice 只用于人物" in error for error in errors))
        self.assertTrue(any("sha256" in error for error in errors))

    def test_duplicate_ids_and_bad_style_are_rejected(self):
        value = bible(subtitle_style={"position": "left", "color": "white"})
        value["entities"][1]["id"] = "主角"
        errors = C.bible_errors(value)
        self.assertTrue(any("id 必须唯一" in error for error in errors))
        self.assertTrue(any("position" in error for error in errors))
        self.assertTrue(any("#RRGGBB" in error for error in errors))

    def test_media_files_must_match_their_sha256(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "06-素材/参考/主角-正面.png"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"front")
            value = bible()
            value["entities"] = [value["entities"][0]]
            value["entities"][0]["references"][0]["sha256"] = hashlib.sha256(b"front").hexdigest()
            self.assertEqual(C.media_problems(value, root), [])
            media.write_bytes(b"changed")
            self.assertIn("SHA-256 不一致", C.media_problems(value, root)[0])


class StateTest(unittest.TestCase):
    def test_template_is_valid_and_derives_entry_and_exit(self):
        self.assertEqual(C.state_errors(STATE, BIBLE), [])
        derived = C.derive(STATE)
        self.assertEqual(derived["SH-002"]["entry"]["entities"]["信封"]["variant"], "default")
        self.assertEqual(derived["SH-002"]["exit"]["entities"]["信封"]["variant"], "信封-已拆")
        self.assertEqual(derived["SH-001"]["entry"]["environment"]["weather"], "雨")

    def test_changes_accumulate_across_non_adjacent_shots(self):
        value = state()
        value["scenes"][0]["shots"] = [
            {"id": "A", "changes": {"entities": {"主角": {"position": "门口"}}}},
            {"id": "B", "changes": {}},
            {"id": "C", "changes": {"entities": {"信封": {"exit": True}, "主角": {"holding": []}}}},
            {"id": "D", "changes": {}},
        ]
        derived = C.derive(value)
        self.assertEqual(derived["B"]["entry"]["entities"]["主角"]["position"], "门口")
        self.assertNotIn("信封", derived["D"]["entry"]["entities"])
        self.assertEqual(C.state_errors(value, BIBLE), [])

    def test_held_items_must_be_present_and_held_once(self):
        value = state()
        value["scenes"][0]["shots"][1]["changes"] = {"entities": {"信封": {"exit": True}}}
        self.assertTrue(any("不在场" in error for error in C.state_errors(value, BIBLE)))
        value = state()
        value["scenes"][0]["baseline"]["entities"]["配角"] = {"holding": ["信封"]}
        errors = C.state_errors(value)
        self.assertTrue(any("同时被" in error for error in errors))

    def test_bible_checks_entities_variants_and_location(self):
        value = state()
        value["scenes"][0]["location_id"] = "主角"
        value["scenes"][0]["shots"][1]["changes"] = {"entities": {"信封": {"variant": "烧毁"}, "路人": {"position": "窗外"}}}
        errors = C.state_errors(value, BIBLE)
        self.assertTrue(any("不是资产库中的地点" in error for error in errors))
        self.assertTrue(any("没有变体 烧毁" in error for error in errors))
        self.assertTrue(any("路人 不在资产库中" in error for error in errors))

    def test_shot_ids_are_unique_across_scenes(self):
        value = state()
        second = copy.deepcopy(value["scenes"][0])
        second["id"] = "EP-001-SC-002"
        value["scenes"].append(second)
        self.assertTrue(any("全片唯一" in error for error in C.state_errors(value)))


class ContinuityCrossCheckTest(unittest.TestCase):
    def test_template_plan_agrees_with_timeline(self):
        problems, warnings = C.continuity_problems(PLAN, C.derive(STATE), BIBLE)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])

    def test_costume_location_and_presence_mismatches_are_reported(self):
        plan = copy.deepcopy(PLAN)
        plan["shots"][0]["entry_state"]["characters"]["主角"]["costume_id"] = "default"
        plan["shots"][0]["exit_state"]["location_id"] = "别处"
        plan["shots"][1]["entry_state"]["characters"]["配角"] = {"costume_id": "x"}
        problems, warnings = C.continuity_problems(plan, C.derive(STATE), BIBLE)
        self.assertTrue(any("costume_id=default" in problem for problem in problems))
        self.assertTrue(any("location_id=别处" in problem for problem in problems))
        self.assertTrue(any("配角" in warning for warning in warnings))


class AnchorTest(unittest.TestCase):
    def test_pack_carries_identity_state_and_changes_for_the_shot(self):
        pack = C.anchor_pack(BIBLE, STATE, "SH-002")
        self.assertEqual((pack["previous_shot"], pack["next_shot"]), ("SH-001", None))
        self.assertEqual(pack["entities"]["信封"]["exit"]["variant"], "信封-已拆")
        self.assertEqual(pack["entities"]["主角"]["entry"]["variant_description"], "深色及膝风衣，领口微湿")
        text = C.anchor_text(pack)
        self.assertIn("本镜变化：旧信封变为封口撕开，信纸露出一角。", text)
        self.assertLess(text.index("主角"), text.index("旧信封"))
        self.assertIn("主角：三十岁左右的短发女性，左眉浅疤，神情克制；不可改变：三十岁左右、短发、左眉有浅疤", text)
        self.assertIn("地点：雨夜客厅，不可改变：老式公寓客厅、门在画面右侧、沙发背靠左墙", text)

    def test_moment_text_describes_one_state_without_changes(self):
        pack = C.anchor_pack(BIBLE, STATE, "SH-002")
        exit_text = C.anchor_text(pack, "exit")
        self.assertIn("镜头 SH-002出点", exit_text)
        self.assertIn("封口撕开，信纸露出一角", exit_text)
        self.assertNotIn("本镜变化", exit_text)
        self.assertIn("封口完好", C.anchor_text(pack, "entry"))

    def test_sha_changes_only_when_this_shot_is_affected(self):
        base = C.pack_sha256(C.anchor_pack(BIBLE, STATE, "SH-002"))
        unrelated = bible()
        unrelated["entities"].append({"id": "路人", "kind": "character", "name": "路人", "identity": ["雨衣"], "variants": {"default": "黑伞"}})
        self.assertEqual(C.pack_sha256(C.anchor_pack(unrelated, STATE, "SH-002")), base)
        changed = bible()
        changed["entities"][0]["identity"].append("戴眼镜")
        self.assertNotEqual(C.pack_sha256(C.anchor_pack(changed, STATE, "SH-002")), base)


class RecordTest(unittest.TestCase):
    def record(self):
        return copy.deepcopy(RECORD)

    def test_template_is_valid_and_bound_to_current_anchors(self):
        self.assertEqual(C.record_errors(RECORD), [])
        self.assertEqual(C.record_problems(RECORD, BIBLE, STATE), ([], []))

    def test_stale_anchors_foreign_references_and_wrong_first_frame(self):
        changed = state()
        changed["scenes"][0]["baseline"]["entities"]["主角"]["position"] = "门口"
        self.assertTrue(any("已过期" in problem for problem in C.record_problems(RECORD, BIBLE, changed)[0]))
        record = self.record()
        record["inputs"]["references"].append("f" * 64)
        record["inputs"]["first_frame"]["shot"] = "SH-009"
        problems, _ = C.record_problems(record, BIBLE, STATE)
        self.assertTrue(any("不属于本镜" in problem for problem in problems))
        self.assertTrue(any("上一镜是 SH-001" in problem for problem in problems))

    def test_missing_anchors_and_text_only_identity(self):
        record = self.record()
        record["inputs"].update(anchors_sha256=None, references=[])
        problems, warnings = C.record_problems(record, BIBLE, STATE)
        self.assertTrue(any("没有绑定锚点包" in problem for problem in problems))
        self.assertTrue(any("只靠文字锚定" in warning for warning in warnings))

    def test_audio_voice_must_match_the_binding(self):
        record = {"format": C.RECORD_FORMAT, "project_id": BIBLE["project_id"], "kind": "audio", "purpose": "animatic_temp",
                  "inputs": {}, "engine": {"provider": "edge-tts", "model": "m"}, "budget": {"billable": False},
                  "submitted_at": "t0", "finished_at": "t1", "status": "succeeded", "errors": [], "selection": None,
                  "outputs": [{"id": "L1", "path": "a.mp3", "sha256": "0" * 64, "entity": "主角", "voice": "zh-CN-YunxiNeural"}]}
        self.assertEqual(C.record_errors(record), [])
        self.assertIn("不一致", C.record_problems(record, BIBLE, STATE)[0][0])

    def test_structural_rules(self):
        record = self.record()
        record["budget"] = {"billable": True}
        record["purpose"] = "animatic_temp"
        record["selection"] = {"output_id": "SH-002-T01", "by": "导演"}
        del record["shot_id"]
        errors = C.record_errors(record)
        self.assertTrue(any("计费任务" in error for error in errors))
        self.assertTrue(any("不能被选为交付候选" in error for error in errors))
        self.assertTrue(any("shot_id" in error for error in errors))


class KeyframeChainTest(unittest.TestCase):
    """资产图 → 关键帧 → 视频：身份沿链路追溯，相邻镜头共用交界帧。"""
    HERO = BIBLE["entities"][0]["references"][0]["sha256"]

    @staticmethod
    def image(sha, shot, moment, references=(), base=None, purpose="candidate"):
        inputs = {"anchors_sha256": None, "moment": moment, "references": list(references), "prompt": "p"}
        if base:
            inputs["base_frame"] = {"path": f"{base}.png", "sha256": base, "use": "edit"}
        return {"format": C.RECORD_FORMAT, "project_id": BIBLE["project_id"], "kind": "image", "purpose": purpose, "shot_id": shot,
                "inputs": inputs, "engine": {"provider": "p", "model": "m"}, "budget": {"billable": False},
                "submitted_at": "t0", "finished_at": "t1", "status": "succeeded", "errors": [], "selection": None,
                "outputs": [{"id": sha[:4], "path": f"{sha[:4]}.png", "sha256": sha}]}

    @staticmethod
    def video(shot, first, last):
        record = copy.deepcopy(RECORD)
        record["shot_id"] = shot
        record["inputs"].update(anchors_sha256=C.pack_sha256(C.anchor_pack(BIBLE, STATE, shot)), references=[],
                                first_frame={"path": "a.png", "sha256": first, "from": "generated"},
                                last_frame={"path": "b.png", "sha256": last, "from": "generated"})
        return record

    def test_identity_is_carried_by_asset_anchored_keyframes(self):
        entry, exit_ = "a" * 64, "b" * 64
        # 出点帧只以入点帧为底图编辑，身份经入点帧追溯到资产图。
        keyframes = {entry: self.image(entry, "SH-001", "exit", [self.HERO]), exit_: self.image(exit_, "SH-002", "exit", base=entry)}
        video = self.video("SH-002", entry, exit_)
        self.assertEqual(C.record_errors(keyframes[exit_]), [])
        problems, warnings = C.record_problems(video, BIBLE, STATE, keyframes=keyframes)
        self.assertEqual((problems, warnings), ([], []))
        self.assertTrue(any("只靠文字锚定" in warning for warning in C.record_problems(video, BIBLE, STATE)[1]))
        _, warnings = C.record_problems(video, BIBLE, STATE, keyframes={entry: keyframes[entry]})
        self.assertTrue(any("追溯不到关键帧记录" in warning for warning in warnings))

    def test_frames_must_be_this_shots_boundaries(self):
        early, late = "c" * 64, "d" * 64
        keyframes = {early: self.image(early, "SH-002", "exit", [self.HERO]), late: self.image(late, "SH-001", "exit", [self.HERO])}
        problems, _ = C.record_problems(self.video("SH-002", early, late), BIBLE, STATE, keyframes=keyframes)
        self.assertTrue(any("首帧对应的关键帧" in problem for problem in problems))
        self.assertTrue(any("尾帧对应的关键帧不是本镜出点" in problem for problem in problems))

    def test_adjacent_videos_share_the_boundary_frame(self):
        first, second = self.video("SH-001", "1" * 64, "2" * 64), self.video("SH-002", "2" * 64, "3" * 64)
        self.assertEqual(C.chain_problems([first, second], STATE), [])
        second["inputs"]["first_frame"]["sha256"] = "4" * 64
        self.assertIn("不是同一张图", C.chain_problems([first, second], STATE)[0])

    def test_asset_images_need_no_shot_and_must_be_registered(self):
        asset = self.image("e" * 64, None, None, purpose="asset")
        asset["inputs"].pop("moment")
        self.assertEqual(C.record_errors(asset), [])
        self.assertTrue(any("尚未登记" in warning for warning in C.record_problems(asset, BIBLE, STATE)[1]))
        asset["outputs"][0]["sha256"] = self.HERO
        self.assertEqual(C.record_problems(asset, BIBLE, STATE), ([], []))
        asset["kind"] = "video"
        self.assertTrue(any("只能是图像" in error for error in C.record_errors(asset)))

    def test_moment_and_base_frame_are_validated(self):
        image = self.image("f" * 64, "SH-001", "middle", base="a" * 64)
        image["inputs"]["base_frame"]["use"] = "copy"
        errors = C.record_errors(image)
        self.assertTrue(any("inputs.moment" in error for error in errors))
        self.assertTrue(any("base_frame.use" in error for error in errors))


class KernelTest(unittest.TestCase):
    def test_contracts_dispatch_through_the_kernel(self):
        for fmt, template in (("vsc.asset-bible/v1", "asset-bible.json"), ("vsc.scene-state/v1", "scene-state.json"),
                              ("vsc.generation-record/v1", "generation-record.json")):
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "vsc_kernel.py"), "contract", "validate", fmt, str(ROOT / "templates" / template)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
