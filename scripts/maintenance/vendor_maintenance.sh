#!/bin/bash
# Run-once manual entry; --plan is read-only. No scheduler, global config or active Vendor changes.
set -u
export PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0
VSC_SCRIPT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VSC_PYTHON="${VSC_VENDOR_PYTHON:-python3}"
if "$VSC_PYTHON" -B "$VSC_SCRIPT_ROOT/vendor_watch.py" "$@"; then
    printf '%s\n' 'VSC Vendor 命令完成（--plan 仅预览）；未采用候选'
    exit 0
else
    vsc_exit_status=$?
    printf 'VSC Vendor 候选维护失败 exit=%s；当前 active Vendor 未变\n' "$vsc_exit_status" >&2
    exit "$vsc_exit_status"
fi
