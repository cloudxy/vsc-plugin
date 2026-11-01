"""Shared one-turn, tool-free local role planner transport; no task or approval owner."""
import json
import subprocess
import tempfile
from pathlib import Path
from vsc.assets.resource_service import ResourceError
from vsc.assets.script_ai import _run_bounded, host_environment


def run_role_plan(packet, source, skill, schema, instructions, *, executable="grok", timeout=120,
                  runner=None, error_prefix="intelligent", invalid_code="invalid_intelligent_plan"):
    with tempfile.TemporaryDirectory(prefix="vsc-role-plan-") as directory:
        prompt=Path(directory)/"input.json"
        prompt.write_text(json.dumps([{"type":"text","text":instructions+json.dumps({"role_context":packet,"skill":skill,"input":source},ensure_ascii=False)}],ensure_ascii=False),encoding="utf8")
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
