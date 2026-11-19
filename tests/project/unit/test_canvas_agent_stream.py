"""Canvas agent stream protocol: Chinese failures, questions, tickets and SSE cursors."""
import unittest

from vsc.production.canvas_agent_stream import (
    classify_agent_failure,
    format_sse_frame,
    format_sse_heartbeat,
    parse_event_cursor,
    reference_only_prompt,
    ticket_blockers,
    validate_question_answers,
)


class CanvasAgentStreamProtocolTests(unittest.TestCase):
    def test_failure_names_become_readable_chinese(self):
        self.assertEqual(classify_agent_failure("rate_limited"), {"code": "rate_limited", "message": "请求较多，请稍后重试"})
        self.assertEqual(classify_agent_failure("quota_exhausted")["message"], "模型服务额度暂不可用，请稍后再试")
        self.assertEqual(classify_agent_failure("provider_unavailable")["message"], "模型服务暂不可用，请稍后重试")
        self.assertEqual(classify_agent_failure("content_rejected")["message"], "内容被模型拒绝，请调整后重试")
        self.assertEqual(classify_agent_failure("provider_timeout")["message"], "模型响应超时，请稍后重试")
        self.assertEqual(classify_agent_failure("provider_connection_error")["message"], "模型服务连接中断，请稍后重试")
        self.assertEqual(classify_agent_failure("turn_timeout")["message"], "本轮处理超时，已停止；发送新消息可以继续")
        self.assertEqual(classify_agent_failure("canvas_agent_host_unavailable")["code"], "provider_unavailable")
        self.assertEqual(classify_agent_failure("canvas_agent_submission_unknown")["code"], "provider_timeout")
        self.assertEqual(classify_agent_failure("canvas_agent_host_failed")["message"], "回合执行失败")
        self.assertEqual(classify_agent_failure("invalid_canvas_plan")["message"], "回合执行失败")
        self.assertEqual(classify_agent_failure("TimeoutError"), {"code": "turn_failed", "message": "回合执行失败"})
        self.assertNotIn("Timeout", classify_agent_failure({"error": "TimeoutError"})["message"])
        self.assertEqual(classify_agent_failure({"reason": "rate_limited"})["message"], "请求较多，请稍后重试")

    def test_reference_prompt_questions_and_ticket_blockers(self):
        self.assertEqual(reference_only_prompt("  保留原文  ", ["n1"]), "保留原文")
        self.assertEqual(reference_only_prompt("  ", ["n1"], []), "请理解所引用的素材。")
        self.assertEqual(reference_only_prompt("", [], ["media"]), "请理解所引用的素材。")
        self.assertEqual(reference_only_prompt("", [], []), "")
        batch = {"items": [
            {"id": "look", "kind": "single", "required": True, "options": [{"id": "a"}, {"id": "b"}], "max_length": 4},
            {"id": "note", "kind": "text", "required": False, "max_length": 4},
        ]}
        missing = validate_question_answers(batch, [{"question_id": "note", "custom_text": "好"}])
        self.assertEqual(missing["message"], "请回答所有必答问题")
        long = validate_question_answers(batch, [
            {"question_id": "look", "selected_option_ids": ["a"], "custom_text": "太长了吧呀"},
        ])
        self.assertEqual(long["message"], "自定义回答最多 4 字")
        skipped = validate_question_answers(batch, None, skip=True)
        self.assertEqual(skipped, {"ok": True, "skipped": True, "answers": []})
        ok = validate_question_answers(batch, [{"question_id": "look", "selected_option_ids": ["a"], "custom_text": ""}])
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["answers"][0]["question_id"], "look")
        future = "2099-01-01T00:00:00+00:00"
        paid = {"ticket_type": "paid", "operation": "生图", "model": "seedream", "unit_price": 2, "quantity": 1, "total_credits": 2, "canvas_version": 1, "expires_at": future}
        self.assertTrue(ticket_blockers(paid, now=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc))["ok"])
        incomplete = dict(paid, model="")
        blocked = ticket_blockers(incomplete)
        self.assertIn("操作与模型", blocked["message"])
        self.assertTrue(blocked["approve_disabled"])
        expired = ticket_blockers(dict(paid, expires_at="2000-01-01T00:00:00+00:00"))
        self.assertEqual(expired["message"], "票据已过期，批准会被服务端拒绝，请让助手重新发起。")
        mismatch = ticket_blockers({"ticket_type": "delete", "canvas_version": 1, "node_count": 2, "node_list": [{"id": "n1"}], "cascade_edge_count": 0, "expires_at": future})
        self.assertEqual(mismatch["message"], "节点清单与数量不一致")

    def test_sse_frame_and_cursor(self):
        frame = format_sse_frame({"seq": 7, "kind": "assistant_delta", "payload": {"text": "雨夜"}})
        self.assertEqual(frame, 'id: 7\nevent: assistant_delta\ndata: {"text":"雨夜","seq":7,"kind":"assistant_delta"}\n\n')
        self.assertEqual(format_sse_heartbeat(), "event: heartbeat\ndata: {}\n\n")
        self.assertEqual(parse_event_cursor(None, None), 0)
        self.assertEqual(parse_event_cursor("12", "4"), 12)
        self.assertEqual(parse_event_cursor("3", "9"), 9)
        self.assertEqual(parse_event_cursor("abc", "9"), 0)
        self.assertEqual(parse_event_cursor("", "9"), 9)
        self.assertEqual(parse_event_cursor("  ", None), 0)
