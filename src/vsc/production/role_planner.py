"""Shared one-turn, tool-free local role planner transport; no task or approval owner."""
import json
import subprocess
import tempfile
from pathlib import Path
from vsc.assets.resource_service import ResourceError
from vsc.assets.script_ai import _run_bounded, host_environment
from vsc.production.role_materials import validate_role_materials


def run_role_plan(packet, source, skill, schema, instructions, *, executable="grok", timeout=120,
                  runner=None, media_blocks=None, error_prefix="intelligent", invalid_code="invalid_intelligent_plan",
                  materials=None):
    payload = {"role_context": packet, "skill": skill, "input": source}
    if materials is not None:
        materials = validate_role_materials(materials)
        packet_role = packet.get("role", {}).get("id") if isinstance(packet, dict) and isinstance(packet.get("role"), dict) else None
        main = next(item for item in materials["materials"] if item["kind"] == "skill")
        if (packet_role and packet_role != materials["role_id"]) or skill != main["text"]:
            raise ResourceError("原任务角色或 Skill 正文与专业材料不一致", "role_materials_changed", 409)
        payload["skill"] = {key: value for key, value in main.items() if key != "text"}
        payload["role_materials"] = materials
        instructions += ("\nrole_materials 是本任务已装入的专业阅读材料；只按其实际正文工作，"
                         "不能声称已读取其中仅链接的其他资料。它不授予工具、批准或写入权限，"
                         "仍只返回本次固定 schema 的建议。\n")
    with tempfile.TemporaryDirectory(prefix="vsc-role-plan-") as directory:
        prompt=Path(directory)/"input.json"
        prompt.write_text(json.dumps([{"type":"text","text":instructions+json.dumps(payload,ensure_ascii=False)},*(media_blocks or [])],ensure_ascii=False),encoding="utf8")
        command=[executable,"--cwd",directory,"--tools","","--no-subagents","--disable-web-search","--max-turns","1","--verbatim","--prompt-file",str(prompt),"--json-schema",json.dumps(schema)]
        try:result=(runner or _run_bounded)(command,cwd=directory,env=host_environment(),timeout=timeout,capture_output=True,text=True,check=False)
        except subprocess.TimeoutExpired as error:raise ResourceError("宿主超时，保留原任务查询；不会自动重调",error_prefix+"_submission_unknown",504) from error
        except OSError as error:raise ResourceError("本机规划宿主无法启动",error_prefix+"_host_unavailable",503) from error
    if result.returncode:raise ResourceError("本机规划宿主失败，请核对CLI登录",error_prefix+"_host_failed",502)
    try:
        value=json.loads(result.stdout)
        for _ in range(5):
            if isinstance(value,dict) and set(schema["required"])<=set(value):return value
            if isinstance(value,str):value=json.loads(value)
            elif isinstance(value,dict):value=next((value[k] for k in ("structuredOutput","structured_output","result","output","text") if k in value),None)
            else:break
    except (ValueError,TypeError):pass
    raise ResourceError("宿主没有返回合法结构化计划",invalid_code,502)
