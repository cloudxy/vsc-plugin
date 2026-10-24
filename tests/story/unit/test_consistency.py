#!/usr/bin/env python3
"""scripts/story/consistency.py 自测。运行：python3 -B tests/run.py --test story.unit.test_consistency"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from support.paths import ROOT
import vsc.story.consistency as C

from support.fixtures.consistency import BIBLE, STATE, PLAN, RECORD, bible, state, RecordFixture


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
    def test_expression_position_and_process_are_validated_and_reach_request_and_observation(self):
        value, places=state(),bible()
        character=places['entities'][0]
        character['expression_baseline']={'description':'relaxed brow', 'reference_sha256':character['references'][0]['sha256']}
        scene=value['scenes'][0]
        scene['spatial']={'frame':'floor','unit':'m'}
        scene['baseline']['entities']['主角'].update(position={'frame':'floor','x':0,'y':0},expression='brow relaxed')
        scene['baseline']['entities']['信封']['position']={'frame':'floor','x':1,'y':0}
        shot=scene['shots'][0]
        shot['in_frame']=['主角','信封']
        shot['changes']={'entities':{'主角':{'position':{'frame':'floor','x':0.5,'y':0},'expression':'eyes widen'}}}
        shot['process']={'enabled':True,'fixed_entities':['信封'],'direction':{'frame':'floor','axis':'x','sign':1},
                         'beats':[{'seconds':0,'action':'prepare'},{'seconds':1,'action':'move and hold'}]}
        self.assertEqual(C.state_errors(value,places),[])
        pack=C.anchor_pack(places,value,shot['id'])
        text=C.anchor_text(pack)
        self.assertIn('eyes widen',text);self.assertIn('未列入本镜 changes',text)
        from vsc.adapters.providers.volc_ark.api import checklist
        observations=checklist(pack,None)
        self.assertTrue(any('预期人数=1' in x for x in observations))
        self.assertTrue(any('仅允许变化' in x for x in observations))
        self.assertTrue(any('eyes widen' in x for x in observations))
        plan={'shots':[{'id':shot['id'],'entry_state':{'location_id':scene['location_id'],
              'characters':{'主角':{'expression':'wrong','position':{'frame':'floor','x':4,'y':0}}}}}]}
        problems,_=C.continuity_problems(plan,C.derive(value),places)
        self.assertTrue(any('expression' in x for x in problems));self.assertTrue(any('position' in x for x in problems))
        for kind in ('fixed','direction','order','frame','nan'):
            bad=copy.deepcopy(value);s=bad['scenes'][0]['shots'][0]
            if kind=='fixed':s['process']['fixed_entities']=['主角']
            if kind=='direction':s['process']['direction']['sign']=-1
            if kind=='order':s['process']['beats'].reverse()
            if kind=='frame':s['changes']['entities']['主角']['position']['frame']='camera'
            if kind=='nan':s['changes']['entities']['主角']['position']['x']=float('nan')
            with self.subTest(kind=kind):self.assertTrue(C.state_errors(bad,places))
        # Explicitly off never introduces process restrictions into old tasks.
        shot['process']={'enabled':False}
        self.assertNotIn('process',C.anchor_pack(places,value,shot['id']))
        character['expression_baseline']['reference_sha256']='f'*64
        self.assertTrue(C.bible_errors(places))

    def test_spatial_axis_uses_world_coordinates_and_explicit_mirror_or_crossing(self):
        value=state();scene=value['scenes'][0]
        scene['spatial']={'frame':'floor','unit':'m'}
        scene['baseline']['entities']['主角']['position']={'frame':'floor','x':0,'y':0}
        scene['baseline']['entities']['信封']['position']={'frame':'floor','x':2,'y':0}
        cam={'spatial':{'frame':'floor','x':1,'y':-2,'axis':['主角','信封'],'mirrored':False}}
        scene['shots']=[{'id':'A','camera':copy.deepcopy(cam),'changes':{}},{'id':'B','camera':copy.deepcopy(cam),'changes':{}}]
        self.assertEqual(C.spatial_problems(C.derive(value)),([],[]))
        # A reverse angle on the same world side is valid.
        scene['shots'][1]['camera']['spatial']['x']=3
        self.assertEqual(C.spatial_problems(C.derive(value)),([],[]))
        scene['shots'][1]['camera']['spatial']['mirrored']=True
        errors,warnings=C.spatial_problems(C.derive(value));self.assertEqual(errors,[]);self.assertTrue(warnings)
        scene['shots'][1]['camera']['spatial']['y']=2
        self.assertTrue(C.spatial_problems(C.derive(value))[0])
        scene['shots'][1]['camera']['spatial']['crossing_reason']='visible orbit establishes new side'
        self.assertEqual(C.spatial_problems(C.derive(value))[0],[])
        scene['baseline']['entities']['信封']['position']='unknown world coordinates'
        errors,warnings=C.spatial_problems(C.derive(value));self.assertEqual(errors,[]);self.assertTrue(any('未判定' in w for w in warnings))

    def test_optional_tension_validates_without_claiming_viewer_emotion(self):
        from vsc.story.script import validation_errors
        doc={'format':'vsc.episode-beats/v1','episodes':[{'id':'E','ending_function':'closure','ending':'door closes',
             'beats':[{'id':'B','action':'return key','change':'access lost','screen_unit_ids':['U']}]}]}
        self.assertEqual(validation_errors(doc),[])
        beat=doc['episodes'][0]['beats'][0]
        for v in (0,5.5,10):
            beat['tension']=v;self.assertEqual(validation_errors(doc),[])
        for v in (-1,999,True,float('nan'),'5'):
            beat['tension']=v
            with self.subTest(value=v):self.assertTrue(validation_errors(doc))

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

    def test_shot_location_overrides_only_that_shot_and_must_be_a_location(self):
        value, places = state(), bible()
        places["entities"].append({"id": "场景-门外-v1", "kind": "location", "name": "门外楼道",
                                   "identity": ["窄楼道"], "variants": {"default": "昏暗"}})
        value["scenes"][0]["shots"][0]["location_id"] = "场景-门外-v1"
        self.assertEqual(C.state_errors(value, places), [])
        derived = C.derive(value)
        self.assertEqual(derived["SH-001"]["location_id"], "场景-门外-v1")
        self.assertEqual(derived["SH-002"]["location_id"], "场景-客厅-v1")
        self.assertEqual(C.anchor_pack(places, value, "SH-001")["location"]["name"], "门外楼道")
        value["scenes"][0]["shots"][0]["location_id"] = "主角"
        self.assertTrue(any("不是资产库中的地点" in e for e in C.state_errors(value, places)))

    def test_in_frame_lists_unique_present_entities(self):
        value = state()
        value["scenes"][0]["shots"][0]["in_frame"] = ["主角", "主角"]
        self.assertTrue(any("in_frame" in e for e in C.state_errors(value, BIBLE)))
        value["scenes"][0]["shots"][0]["in_frame"] = ["路人"]
        self.assertTrue(any("不在场" in e for e in C.state_errors(value, BIBLE)))
        value["scenes"][0]["shots"][0]["in_frame"] = []
        self.assertEqual(C.state_errors(value, BIBLE), [])

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
        self.assertIn("旧信封变为封口撕开，信纸露出一角", text)
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

    def test_in_frame_keeps_off_frame_entities_out_of_the_prompt(self):
        self.assertNotIn("off_frame", C.anchor_pack(BIBLE, STATE, "SH-002"))
        value = state()
        value["scenes"][0]["shots"][1]["in_frame"] = ["信封"]
        pack = C.anchor_pack(BIBLE, value, "SH-002")
        self.assertEqual(set(pack["entities"]), {"信封"})
        self.assertEqual(pack["off_frame"], [{"id": "主角", "name": "主角"}])
        self.assertNotIn("主角", pack["changes"]["entities"])
        text = C.anchor_text(pack)
        self.assertIn("画外在场、不得入画：主角。", text)
        self.assertNotIn("短发", text)
        self.assertIn("旧信封变为封口撕开，信纸露出一角", text)
        # 在场不等于入画：状态照常推导，画外的人仍可被听见。
        self.assertEqual(C.derive(value)["SH-002"]["exit"]["entities"]["主角"]["pose"], "站起")
        self.assertIn("主角", C.audio_pack(BIBLE, value, "SH-002")["entities"])

    def test_sha_changes_only_when_this_shot_is_affected(self):
        base = C.pack_sha256(C.anchor_pack(BIBLE, STATE, "SH-002"))
        unrelated = bible()
        unrelated["entities"].append({"id": "路人", "kind": "character", "name": "路人", "identity": ["雨衣"], "variants": {"default": "黑伞"}})
        self.assertEqual(C.pack_sha256(C.anchor_pack(unrelated, STATE, "SH-002")), base)
        changed = bible()
        changed["entities"][0]["identity"].append("戴眼镜")
        self.assertNotEqual(C.pack_sha256(C.anchor_pack(changed, STATE, "SH-002")), base)


class RecordTest(RecordFixture, unittest.TestCase):

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

    def test_audio_asset_checks_voice_provider_and_resource(self):
        value = bible()
        value["entities"][0]["voice"] = {"engine": "doubao_speech", "voice": "sample-voice", "rights": "unknown", "resource_id": "seed-tts-2.0"}
        record = self.record()
        record.update(kind="audio", purpose="asset", shot_id=None,
                      engine={"provider": "doubao_speech", "model": "seed-tts-2.0", "params": {"resource_id": "seed-tts-2.0"}},
                      inputs={}, outputs=[{"id": "voice", "path": "voice.wav", "sha256": "0" * 64, "entity": value["entities"][0]["id"], "voice": "sample-voice"}])
        self.assertEqual(C.record_errors(record), [])
        self.assertEqual(C.record_problems(record, value, STATE), ([], []))
        record["engine"]["params"]["resource_id"] = "seed-icl-2.0"
        self.assertTrue(any("声音模型资源" in x for x in C.record_problems(record, value, STATE)[0]))
        record["engine"]["provider"] = "other"
        self.assertTrue(any("声音供应商" in x for x in C.record_problems(record, value, STATE)[0]))

    def test_malformed_record_values_are_reported_without_crashing(self):
        self.assertTrue(C.record_errors([]))
        record = self.record()
        record["outputs"][0]["id"] = ["bad"]
        record["selection"] = {"output_id": ["bad"], "by": "用户"}
        self.assertTrue(any("id 必须唯一" in error for error in C.record_errors(record)))
        self.assertTrue(any("selection" in error for error in C.record_errors(record)))



class ReferenceAndPerformanceTest(unittest.TestCase):
    def test_reference_variants_filter_unrelated_costume_and_preserve_generic_identity(self):
        value = bible()
        hero = value["entities"][0]
        hero["references"] += [
            {"path": "default.png", "sha256": "a" * 64, "media_type": "image", "purpose": "appearance", "variants": ["default"]},
            {"path": "coat.png", "sha256": "b" * 64, "media_type": "image", "purpose": "appearance", "variants": ["主角-风衣-v1"]}]
        self.assertEqual(C.bible_errors(value), [])
        pack = C.anchor_pack(value, STATE, "SH-002")
        self.assertEqual({ref["sha256"] for ref in pack["entities"]["主角"]["references"]}, {"0" * 64, "b" * 64})
        record = copy.deepcopy(RECORD)
        record["inputs"]["anchors_sha256"] = C.pack_sha256(pack)
        record["inputs"]["references"].append({"sha256": "a" * 64, "media_type": "image", "purpose": "appearance", "entity_id": "主角"})
        self.assertTrue(any("变体" in p for p in C.record_problems(record, value, STATE)[0]))
        before = C.pack_sha256(pack)
        hero["references"][1]["sha256"] = "c" * 64
        self.assertEqual(C.pack_sha256(C.anchor_pack(value, STATE, "SH-002")), before)
        hero["references"][2].pop("variants")
        self.assertTrue(any("variants" in p for p in C.bible_errors(value)))

    def test_entering_in_special_variant_does_not_include_absent_default(self):
        value, timeline = bible(), state()
        value["entities"][0]["references"].append(
            {"path": "default.png", "sha256": "a" * 64, "purpose": "appearance", "variants": ["default"]})
        del timeline["scenes"][0]["baseline"]["entities"]["主角"]
        timeline["scenes"][0]["baseline"]["entities"]["信封"]["position"] = "桌面"
        timeline["scenes"][0]["shots"][0]["changes"]["entities"]["主角"].update(variant="主角-风衣-v1", holding=["信封"])
        self.assertNotIn("a" * 64, {ref["sha256"] for ref in C.anchor_pack(value, timeline, "SH-001")["entities"]["主角"]["references"]})

    def test_multimodal_inputs_preserve_identity_and_validate_entity_and_media(self):
        value = bible()
        hero = value["entities"][0]
        hero["references"].append({"path": "action.mp4", "sha256": "b" * 64, "media_type": "video", "purpose": "action"})
        value["entities"][2]["sound"]["sha256"] = "c" * 64
        record = copy.deepcopy(RECORD)
        record["inputs"].update(anchors_sha256=C.pack_sha256(C.anchor_pack(value, STATE, "SH-002")),
                                audio_anchors_sha256=C.pack_sha256(C.audio_pack(value, STATE, "SH-002")))
        record["inputs"]["references"] += [
            {"sha256": "b" * 64, "media_type": "video", "role": "reference_video", "purpose": "action", "entity_id": "主角"},
            {"sha256": "c" * 64, "media_type": "audio", "role": "reference_audio", "purpose": "sound", "entity_id": "信封"}]
        self.assertEqual(C.record_errors(record), [])
        self.assertEqual(C.record_problems(record, value, STATE), ([], []))
        record["inputs"]["references"][1]["entity_id"] = "信封"
        self.assertTrue(any("实体绑定" in p for p in C.record_problems(record, value, STATE)[0]))
        record["inputs"]["references"][1]["entity_id"] = "主角"
        record["inputs"]["references"] = record["inputs"]["references"][1:]
        self.assertTrue(any("只靠文字锚定" in p for p in C.record_problems(record, value, STATE)[1]))
        record["inputs"]["references"][0]["purpose"] = "identity"
        self.assertTrue(any("媒体类别与用途" in p for p in C.record_errors(record)))

    def test_sound_change_affects_only_audio_consumers(self):
        value = bible()
        visual = C.pack_sha256(C.anchor_pack(value, STATE, "SH-002"))
        audio = C.pack_sha256(C.audio_pack(value, STATE, "SH-002"))
        record = copy.deepcopy(RECORD)
        record["inputs"]["audio_anchors_sha256"] = audio
        value["entities"][0]["voice"]["voice"] = "changed-voice"
        self.assertEqual(C.pack_sha256(C.anchor_pack(value, STATE, "SH-002")), visual)
        self.assertNotEqual(C.pack_sha256(C.audio_pack(value, STATE, "SH-002")), audio)
        self.assertEqual(C.record_problems(RECORD, value, STATE), ([], []))
        self.assertTrue(any("声音基线" in p for p in C.record_problems(record, value, STATE)[0]))

    def test_performance_accumulates_and_camera_direction_is_not_world_orientation(self):
        timeline = state()
        timeline["scenes"][0]["shots"][0]["changes"]["entities"]["主角"].update(gaze="窗外", orientation="向西", note="呼吸变慢")
        timeline["scenes"][0]["shots"][1]["camera"] = {"screen_direction": "向画面左侧"}
        self.assertEqual(C.state_errors(timeline, BIBLE), [])
        entry = C.derive(timeline)["SH-002"]["entry"]["entities"]["主角"]
        self.assertEqual((entry["pose"], entry["gaze"], entry["orientation"], entry["holding_hand"]), ("抬头看向门口", "窗外", "向西", "right"))
        words = C.anchor_text(C.anchor_pack(BIBLE, timeline, "SH-002"), "entry")
        for phrase in ("姿势：抬头", "视线：窗外", "世界朝向：向西", "持物手：right", "状态备注：呼吸变慢", "screen_direction=向画面左侧"):
            self.assertIn(phrase, words)
        timeline["scenes"][0]["shots"][0]["changes"]["entities"]["主角"]["screen_direction"] = "left"
        self.assertTrue(any("未知字段" in p for p in C.state_errors(timeline, BIBLE)))

    def test_voice_media_never_anchors_a_character_image(self):
        image = KeyframeChainTest.image("a" * 64, "SH-002", "entry")
        image["inputs"]["references"] = [{"sha256": "0" * 64, "media_type": "audio", "purpose": "voice", "role": "reference_audio"}]
        self.assertEqual(C.identity_references(image, {}), set())


class KeyframeChainTest(unittest.TestCase):
    """资产图 → 关键帧 → 视频：身份沿链路追溯，相邻镜头共用交界帧。"""
    HERO = BIBLE["entities"][0]["references"][0]["sha256"]

    @staticmethod
    def bridge(strategy="match_frame"):
        return {"shots": [{"id": "SH-001", "bridge_to_next": {"strategy": strategy, "match_fields": []}}, {"id": "SH-002"}]}

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
        self.assertEqual(C.chain_problems([first, second], STATE, self.bridge()), [])
        second["inputs"]["first_frame"]["sha256"] = "4" * 64
        self.assertIn("不是同一张图", C.chain_problems([first, second], STATE, self.bridge())[0])

    def test_actual_tail_precedes_the_requested_tail(self):
        first = self.video("SH-001", "1" * 64, "2" * 64)
        second = self.video("SH-002", "2" * 64, "3" * 64)
        first["outputs"].append({"id": "actual-tail", "path": "tail.png", "sha256": "4" * 64, "role": "last_frame"})
        self.assertIn("不是同一张图", C.chain_problems([first, second], STATE, self.bridge())[0])
        second["inputs"]["first_frame"]["sha256"] = "4" * 64
        self.assertEqual(C.chain_problems([first, second], STATE, self.bridge()), [])
        first["outputs"].pop()
        self.assertIn("不是同一张图", C.chain_problems([first, second], STATE, self.bridge())[0])
        second["inputs"]["first_frame"]["sha256"] = "2" * 64
        self.assertEqual(C.chain_problems([first, second], STATE, self.bridge()), [])

    def test_identical_actual_tails_keep_both_shot_boundaries(self):
        shared = "5" * 64
        first = self.video("SH-001", "1" * 64, shared)
        first["inputs"]["references"] = [self.HERO]
        second = self.video("SH-002", shared, shared)
        for record in (first, second):
            record["outputs"].append({"id": "tail", "path": "tail.png", "sha256": shared, "role": "last_frame"})
        for records in ([first, second], [second, first]):
            keyframes = C.keyframe_index(records, BIBLE["project_id"])
            self.assertIn(shared, keyframes)
            self.assertEqual({C.moment_of(source) for source in keyframes[shared]}, {("SH-001", "exit"), ("SH-002", "exit")})
            self.assertEqual(C.record_problems(second, BIBLE, STATE, keyframes=keyframes), ([], []))
            self.assertEqual(C.chain_problems(records, STATE, self.bridge()), [])

    def test_multi_take_selection_is_explicit_and_order_independent(self):
        chosen = self.video("SH-001", "1" * 64, "2" * 64)
        chosen["outputs"][0]["id"] = "chosen"
        rejected = self.video("SH-001", "1" * 64, "9" * 64)
        rejected["outputs"][0]["id"] = "other"
        second = self.video("SH-002", "2" * 64, "3" * 64)
        for records in ([chosen, rejected, second], [second, rejected, chosen]):
            self.assertTrue(any("歧义" in p for p in C.chain_problems(records, STATE, self.bridge())))
            self.assertEqual(C.chain_problems(records, STATE, self.bridge(), {"SH-001": "chosen"}), [])
            self.assertTrue(any("不是同一张图" in p for p in C.chain_problems(records, STATE, self.bridge(), {"SH-001": "other"})))
        chosen["selection"] = {"output_id": "chosen", "by": "synthetic fixture reviewer"}
        self.assertEqual(C.chain_problems([rejected, chosen, second], STATE, self.bridge()), [])
        self.assertIsNone(rejected["selection"])
        self.assertTrue(any("未匹配" in p for p in C.chain_problems([chosen, second], STATE, self.bridge(), {"SH-001": "missing"})))
        self.assertTrue(any("未匹配" in p for p in C.chain_problems([chosen, second], STATE, self.bridge(),
                                                              {"SH-001": {"output_id": "chosen", "sha256": "9" * 64}})))

    def test_cut_strategy_checks_state_instead_of_requiring_equal_pixels(self):
        first, second = self.video("SH-001", "1" * 64, "2" * 64), self.video("SH-002", "8" * 64, "3" * 64)
        plan = self.bridge("hard_cut")
        field = "characters.主角.orientation"
        plan["shots"][0].update(exit_state={"characters": {"主角": {"orientation": "east"}}})
        plan["shots"][1].update(entry_state={"characters": {"主角": {"orientation": "east"}}})
        plan["shots"][0]["bridge_to_next"]["match_fields"] = [field]
        self.assertEqual(C.chain_problems([first, second], STATE, plan), [])
        plan["shots"][1]["entry_state"]["characters"]["主角"]["orientation"] = "west"
        self.assertTrue(any(field in p for p in C.chain_problems([first, second], STATE, plan)))
        plan["shots"][0]["bridge_to_next"]["match_fields"] = ["characters.主角.gaze"]
        self.assertTrue(any("缺失" in p for p in C.chain_problems([first, second], STATE, plan)))

    def test_missing_bridge_is_reported_and_legacy_previous_exit_is_explicit(self):
        first, second = self.video("SH-001", "1" * 64, "2" * 64), self.video("SH-002", "2" * 64, "3" * 64)
        self.assertTrue(any("bridge.strategy" in p for p in C.chain_problems([first, second], STATE)))
        second["inputs"]["first_frame"].update({"from": "previous_exit", "shot": "SH-001"})
        self.assertEqual(C.chain_problems([first, second], STATE), [])
        self.assertTrue(any("bridge.strategy" in p for p in C.chain_problems([first, second], STATE, {"shots": []})))
        first["outputs"].append({"id": "tail", "path": "tail.png", "sha256": "2" * 64, "role": "last_frame"})
        first["selection"] = {"output_id": "tail", "by": "synthetic fixture reviewer"}
        self.assertTrue(any("主输出" in p for p in C.chain_problems([first, second], STATE, self.bridge())))

    def test_same_hash_does_not_make_the_wrong_boundary_valid(self):
        shared = "6" * 64
        wrong = self.image(shared, "SH-002", "exit", [self.HERO])
        second = self.video("SH-002", shared, shared)
        problems, warnings = C.record_problems(second, BIBLE, STATE, keyframes=C.keyframe_index([wrong]))
        self.assertTrue(any("首帧对应的关键帧" in item for item in problems))
        # 本镜尾帧仍可提供身份来源，不能把它误当作入点边界。
        self.assertEqual(warnings, [])

    def test_failed_foreign_and_malformed_sources_cannot_anchor_video(self):
        entry, exit_ = "7" * 64, "8" * 64
        video = self.video("SH-002", entry, exit_)
        sources = []
        failed = self.image(entry, "SH-001", "exit", [self.HERO])
        failed["status"] = "failed"
        sources.append(failed)
        foreign = self.image(entry, "SH-001", "exit", [self.HERO])
        foreign["project_id"] = "another-project"
        sources.append(foreign)
        malformed = self.image(entry, "SH-001", "exit", [self.HERO])
        malformed["outputs"][0].pop("sha256")
        sources.append(malformed)
        for source in sources:
            self.assertNotIn(entry, C.keyframe_index([source], BIBLE["project_id"]))
            # 外部调用方传旧索引也不能绕过来源核验。
            problems, warnings = C.record_problems(video, BIBLE, STATE, keyframes={entry: source})
            self.assertEqual(problems, [])
            self.assertTrue(any("只靠文字锚定" in item for item in warnings))
        self.assertEqual(C.keyframe_index([{}, None, [], malformed]), {})

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


class VisualReportTest(unittest.TestCase):
    @staticmethod
    def report():
        return {"format": C.VISUAL_FORMAT, "project_id": BIBLE["project_id"], "entities": ["主角"],
                "subject": {"path": "portrait.png", "sha256": "9" * 64},
                "engine": {"provider": "volcengine_ark", "model": "vision"}, "advisory": True,
                "checklist": ["主角在场", "衣服完整"],
                "results": [{"item": "主角在场", "verdict": "pass", "evidence": "画面中有主角"},
                            {"item": "衣服完整", "verdict": "unsure", "evidence": "衣服下部被遮挡"}], "issues": []}

    def test_complete_checklist_and_evidence_are_valid(self):
        self.assertEqual(C.visual_errors(self.report()), [])

    def test_missing_evidence_and_advisory_are_rejected(self):
        report = self.report()
        report["results"][0]["evidence"] = " "
        report["advisory"] = False
        errors = C.visual_errors(report)
        self.assertTrue(any("evidence" in item for item in errors))
        self.assertTrue(any("advisory" in item for item in errors))

    def test_checklist_requires_exactly_one_result_per_item(self):
        report = self.report()
        report["results"].pop()
        self.assertTrue(any("遗漏" in item for item in C.visual_errors(report)))
        report = self.report()
        report["results"].append(copy.deepcopy(report["results"][0]))
        self.assertTrue(any("重复核对" in item for item in C.visual_errors(report)))
        report = self.report()
        report["results"][0]["item"] = "自选检查项"
        self.assertTrue(any("之外" in item for item in C.visual_errors(report)))
        report = self.report()
        report["checklist"] = ["主角在场", "主角在场"]
        self.assertTrue(any("重复条目" in item for item in C.visual_errors(report)))
        for checklist in (None, [], "主角在场", [None]):
            report = self.report()
            report["checklist"] = checklist
            self.assertTrue(any("checklist" in item for item in C.visual_errors(report)))




if __name__ == "__main__":
    unittest.main()
