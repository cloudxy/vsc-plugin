"""Project-shared native-unit budgets, reserved before a paid submission."""
import json
import math
from sqlalchemy import func, insert, select, update
from vsc.assets.resource_service import Conflict, ResourceError, required
from . import schema as S
from .values import clean, new_id, checked_id

UNITS = frozenset({"remote_jobs", "images", "video_seconds", "audio_jobs", "speech_chars", "vision_jobs"})


def native_units(request):
    modality = request["modality"]
    result = {"remote_jobs": 1}
    if modality == "image":
        result["images"] = 1
    elif modality == "video":
        if request.get("operation") == "edit":
            duration = request.get("source_duration_ms")
            if type(duration) is not int or duration <= 0:
                raise ResourceError("视频编辑预算需要核实源片时长", "invalid_native_units")
            return {"remote_jobs": 1, "video_seconds": math.ceil(duration / 1000)}
        duration = request.get("duration_ms", 5000)
        if type(duration) is not int or duration < 1000 or duration % 1000:
            raise ResourceError("正式视频预算需要正整数秒", "invalid_native_units")
        result["video_seconds"] = duration // 1000
    elif modality == "audio":
        result.update(audio_jobs=1, speech_chars=len(request["prompt"]))
    return result


def operation_key(request, candidate_no):
    key = "%s:%s:%s:%s" % ("asset" if request.get("asset_id") else "series",
        request.get("asset_id") or request["shot_id"], request["purpose"], candidate_no)
    if request.get("operation"):
        key += ":" + request["operation"] + ":" + request["source_sha256"]
    return key


class BudgetRepository:
    @staticmethod
    def _recorded_bills(conn, project_id, job_id=None):
        query = select(S.job_events.c.job_id, S.job_events.c.evidence).where(
            S.job_events.c.project_id == project_id, S.job_events.c.event_type == 'bill_recorded')
        if job_id is not None:
            query = query.where(S.job_events.c.job_id == job_id)
        return {row['job_id']: row['evidence']['actual_cost'] for row in conn.execute(query).mappings()}

    def record_generation_bill(self, project_id, payload, **kw):
        def work(conn, project):
            job = self._one(conn, S.generation_jobs, project['id'], checked_id(required(payload, 'job_id')))
            if job['status'] not in {'succeeded', 'failed', 'cancelled'}:
                raise Conflict('账单只能登记在已结束任务上', 'bill_job_not_terminal')
            from vsc.production.quotes import checked_bill
            try:
                bill = checked_bill(required(payload, 'actual_cost'))
            except ValueError as error:
                raise ResourceError(str(error), 'invalid_generation_bill') from error
            old = self._recorded_bills(conn, project['id'], job['id']).get(job['id'])
            if old is not None:
                if old != bill:
                    raise Conflict('已有固定账单，不能覆盖；请另行核对原记录', 'generation_bill_conflict')
                return {'job_id': job['id'], 'actual_cost': old}
            conn.execute(insert(S.job_events).values(project_id=project['id'], id=new_id(), job_id=job['id'],
                event_type='bill_recorded', evidence={'actual_cost': bill, 'actor': kw.get('actor')}))
            return {'job_id': job['id'], 'actual_cost': bill}
        return self._mutate(project_id, 'record_generation_bill', payload, callback=work, **kw)

    def job_quote_status(self, project_id, job_id):
        from vsc.production.quotes import reconcile_quote
        with self.engine.connect() as conn:
            project = self._project(conn, checked_id(project_id))
            job = self._one(conn, S.generation_jobs, project['id'], checked_id(job_id))
            event = conn.execute(select(S.job_events.c.evidence).where(S.job_events.c.project_id == project['id'],
                S.job_events.c.job_id == job['id'], S.job_events.c.event_type == 'intent_recorded').limit(1)).scalar_one_or_none()
            quote = (event or {}).get('generation_quote')
            actual = {row['unit']: row['actual'] for row in conn.execute(select(S.job_budget_reservations).where(
                S.job_budget_reservations.c.project_id == project['id'], S.job_budget_reservations.c.job_id == job['id'],
                S.job_budget_reservations.c.actual.is_not(None))).mappings()}
            return clean({'job_id': job['id'], 'status': job['status'], 'quote': quote,
                'reconciliation': dict(reconcile_quote(quote, actual, actual_cost=self._recorded_bills(conn, project['id'], job['id']).get(job['id']), policy=(event or {}).get('quote_policy')),
                    actual_units_reported=bool(actual)) if quote else None})

    @staticmethod
    def _limits(conn, p):
        values = {}
        for row in conn.execute(select(S.budget_limit_versions).where(S.budget_limit_versions.c.project_id == p)
                .order_by(S.budget_limit_versions.c.revision.desc())).mappings():
            values.setdefault(row["unit"], dict(row))
        return values

    @staticmethod
    def _used(conn, p):
        result = {}
        for row in conn.execute(select(S.job_budget_reservations).where(
                S.job_budget_reservations.c.project_id == p, S.job_budget_reservations.c.status != "released")).mappings():
            amount = row["actual"] if row["status"] == "settled" and row["actual"] is not None else row["bound"]
            result[row["unit"]] = result.get(row["unit"], 0) + amount
        return result

    def configure_budget(self, project_id, payload, actor, **kw):
        def work(conn, project):
            limits = required(payload, "limits")
            if not isinstance(limits, dict) or not limits or set(limits) - UNITS:
                raise ResourceError("预算需要明确的原生单位limits", "invalid_budget")
            used = self._used(conn, project["id"])
            reason = required(payload, "reason")
            for unit, amount in limits.items():
                if type(amount) is not int or amount < 0:
                    raise ResourceError("原生单位预算必须是非负整数", "invalid_budget")
                if amount < used.get(unit, 0):
                    raise Conflict("新上限低于已占用原生单位", "budget_below_committed")
                conn.execute(insert(S.budget_limit_versions).values(project_id=project["id"], revision=project["revision"] + 1,
                    unit=unit, amount=amount, actor=actor, reason=reason))
            return {"limits": limits}
        return self._mutate(project_id, "configure_budget", payload, actor=actor, callback=work, **kw)

    def budget_status(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            limits, used = self._limits(conn, project["id"]), self._used(conn, project["id"])
            from vsc.production.quotes import reconcile_quote
            actuals = {}
            for row in conn.execute(select(S.job_budget_reservations).where(S.job_budget_reservations.c.project_id == project['id'],
                    S.job_budget_reservations.c.actual.is_not(None))).mappings():
                actuals.setdefault(row['job_id'], {})[row['unit']] = row['actual']
            comparisons = []
            bills = self._recorded_bills(conn, project['id'])
            for row in conn.execute(select(S.job_events.c.job_id, S.job_events.c.evidence).where(
                    S.job_events.c.project_id == project['id'], S.job_events.c.event_type == 'intent_recorded')).mappings():
                quote = row['evidence'].get('generation_quote')
                if quote:
                    actual = actuals.get(row['job_id'])
                    comparisons.append(dict(reconcile_quote(quote, actual or {}, actual_cost=bills.get(row['job_id']), policy=row['evidence'].get('quote_policy')),
                        job_id=row['job_id'], actual_units_reported=actual is not None))
            return clean({"project_id": project["id"], "revision": project["revision"],
                "limits": {unit: value["amount"] for unit, value in limits.items()}, "used": used,
                "remaining": {unit: value["amount"] - used.get(unit, 0) for unit, value in limits.items()},
                "quote_reconciliation": comparisons,
                "bounded_reservations": [dict(r) for r in conn.execute(select(S.job_budget_reservations).where(
                    S.job_budget_reservations.c.project_id == project["id"], S.job_budget_reservations.c.actual.is_(None),
                    S.job_budget_reservations.c.status != "released")).mappings()]})

    def _reserve_budget(self, conn, project, job):
        run = self._one(conn, S.artifact_versions, project["id"], job["run_version_id"])
        document = json.loads(run["document"])
        model = conn.execute(select(S.provider_models).where(S.provider_models.c.id == job['model_id'])).mappings().one()
        from .quotes import check_pinned
        check_pinned(document, model, job['request_payload'], job['candidate_no'])
        if project.get("profile_snapshot", {}).get("contract_policy") != "production-v2" and document.get("phase") != "trial":
            return
        limits = self._limits(conn, project["id"])
        requested = native_units(job["request_payload"])
        if not set(requested) <= set(limits):
            raise ResourceError("正式项目须先配置全部所需原生单位预算", "budget_not_configured")
        operation = operation_key(job["request_payload"], job["candidate_no"])
        bound = document.get("operations", {}).get(operation)
        if not isinstance(bound, dict) or any(type(bound.get(unit)) is not int or bound[unit] < value for unit, value in requested.items()):
            raise ResourceError("run.operations没有授权本任务原生单位", "run_budget_unauthorized")
        if set(bound) - UNITS:
            raise ResourceError("run.operations含未知原生单位", "invalid_native_units")
        used = self._used(conn, project["id"])
        for unit, amount in requested.items():
            if used.get(unit, 0) + amount > limits[unit]["amount"]:
                raise Conflict("项目共享预算不足: " + unit, "budget_exceeded")
            conn.execute(insert(S.job_budget_reservations).values(project_id=project["id"], id=new_id(), job_id=job["id"],
                unit=unit, bound=amount, status="reserved", limit_revision=limits[unit]["revision"]))

    def _settle_budget(self, conn, p, job, actual_units=None):
        if actual_units is not None and (not isinstance(actual_units, dict) or set(actual_units) - UNITS
                or any(type(v) is not int or v < 0 for v in actual_units.values())):
            raise ResourceError("实际原生单位无效", "invalid_native_units")
        rows = conn.execute(select(S.job_budget_reservations).where(S.job_budget_reservations.c.project_id == p,
            S.job_budget_reservations.c.job_id == job["id"])).mappings().all()
        for row in rows:
            actual = actual_units.get(row["unit"]) if actual_units is not None else None
            if actual is not None and actual > row["bound"]:
                raise ResourceError("实际用量超过批准边界，需要人工核对超额", "budget_actual_exceeds_bound")
            conn.execute(update(S.job_budget_reservations).where(S.job_budget_reservations.c.project_id == p,
                S.job_budget_reservations.c.id == row["id"]).values(actual=actual, status="released" if actual == 0 else "settled"))
