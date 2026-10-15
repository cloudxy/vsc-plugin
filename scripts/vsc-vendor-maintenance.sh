#!/bin/bash
# Compatible entry; maintenance implementation owns behavior.
VSC_SCRIPT_ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$VSC_SCRIPT_ROOT/../tools/maintenance/vsc-vendor-maintenance.sh" "$@"
