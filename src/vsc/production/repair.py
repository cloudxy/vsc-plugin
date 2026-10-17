"""Compare local repair proposals against actual immutable downstream uses."""
from vsc.production.quality_plan import _number, _union

KINDS = {'retain_interval', 'crop', 'local_edit', 'composite', 'replace_asset', 'edit_cut', 'regenerate'}


def compare_repairs(plan, usage, impact_graph=None):
    """Read-only recommendation. Applying a repair still uses normal operations.

Usage is returned by ResourceService.get_media_usage, not invented by the plan.
Frozen jobs/timelines/renders stay immutable; replacing a future selection does
not silently replace any of these consumers.
"""
    problems, choices = [], []
    if not isinstance(plan, dict) or plan.get('media_id') != usage.get('media_id'):
        return {'status': 'blocked', 'problems': ['修复计划必须绑定实际查询媒体'], 'execution_authorized': False}
    impacts = {name: rows for name, rows in usage.items() if name in {'current_bindings', 'job_inputs', 'operation_inputs', 'timeline_items', 'render_inputs'}}
    incomplete = [name for name, total in usage.get('totals', {}).items() if name in impacts and total > len(impacts[name])]
    if not impact_graph or impact_graph.get('revision') != usage.get('revision') or not impact_graph.get('impact', {}).get('complete'):
        incomplete.append('transitive_impact')
    consumers = [node for node in (impact_graph or {}).get('nodes', [])
                 if node.get('impact', {}).get('classification') == 'affected_pending_review']
    options = plan.get('options')
    if not isinstance(options, list) or not options:
        problems.append('需要明确修复备选 options')
        options = []
    for option in options:
        if not isinstance(option, dict) or option.get('kind') not in KINDS:
            problems.append('未知修复路线')
            continue
        kind = option['kind']
        if not isinstance(option.get('reason'), str) or not option['reason'].strip():
            problems.append(kind + ' 缺少缺陷与用途依据')
        retained = None
        if kind == 'retain_interval':
            try:
                duration = plan.get('generated_seconds')
                if not _number(duration) or duration == 0:
                    raise ValueError('须有原媒体实测时长')
                retained = _union(option.get('intervals'), duration)
            except ValueError as exc:
                problems.append(str(exc))
        effort = option.get('estimated_active_seconds')
        if effort is not None and not _number(effort):
            problems.append(kind + ' 工时估算无效')
        costs = option.get('estimated_costs', [])
        if not isinstance(costs, list) or any(not isinstance(c, dict) or not c.get('unit') or not _number(c.get('amount')) for c in costs):
            problems.append(kind + ' 费用估算须明确单位和非负数值')
        choices.append({'kind': kind, 'reason': option.get('reason'), 'retained_seconds': retained,
            'estimated_active_seconds': effort, 'estimated_costs': costs,
            'actual_cost': None, 'source_media_unchanged': kind == 'retain_interval',
            'media_review_reusable': False, 'review_reuse': 'requires_fixed_media_dependencies_purpose_criteria_authorization',
            'purpose_and_cut_review_required': True, 'new_media_review_required': kind != 'retain_interval',
            'frozen_consumers_to_review': impacts, 'transitive_consumers_to_review': consumers, 'automatic_replacement': False})
    return {'format': 'vsc.repair-comparison/v1', 'media_id': usage.get('media_id'), 'revision': usage.get('revision'),
        'status': 'blocked' if problems else 'incomplete' if incomplete else 'ready_for_review',
        'execution_authorized': False, 'problems': problems, 'incomplete_impact_groups': incomplete,
        'choices': choices, 'cost_basis': 'estimates_only; actual_unknown'}
