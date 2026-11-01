"""Management and batch readiness projections; all facts remain in original owners."""


class ProductionPlatformServiceMixin:
    def get_execution_authorizations(self, project_id):
        import json
        from vsc.assets.resource_service import Conflict
        listing = self.list_artifacts(project_id)
        rows = []
        for item in listing["items"]:
            if item["artifact_type"] not in {"production-run", "vsc.production_run"} or not item["approved"]:
                continue
            artifact = self.get_artifact_version(project_id, item["id"])
            doc = artifact["document"]
            doc = json.loads(doc) if isinstance(doc, (str, bytes)) else doc
            policy = doc.get("execution_policy") or {}
            authorization = policy.get("authorization") or {}
            if authorization.get("mode") == "new_batch":
                rows.append(dict(id=item["id"], sha256=item["sha256"], reason=authorization["reason"],
                    created_at=item["created_at"], stop_submitting_at=policy["stop_submitting_at"]))
        if self.get_project(project_id)["revision"] != listing["revision"]:
            raise Conflict("制作授权读取期间已改变，请重新读取")
        return dict(items=rows, revision=listing["revision"])

    def preview_first_production(self, project_id, payload):
        from vsc.assets.resource_service import ResourceError, Conflict
        from vsc.production.quotes import fingerprint
        from vsc.production.run_policy import policy_errors
        from vsc.production.run_authorization import normalize_request
        if (not isinstance(payload, dict) or set(payload) - {"episode_id", "shots", "model_id", "purpose", "execution_policy", "commerce_account_actor"}
                or not isinstance(payload.get("shots"), list) or not 1 <= len(payload["shots"]) <= 50):
            raise ResourceError("制作方案需要本集 1–50 个镜头与实际模型")
        errors = policy_errors(payload.get("execution_policy"))
        if payload.get("execution_policy") is None or errors:
            raise ResourceError("；".join(errors) or "需要固定本批时限与次数")
        shots, purpose = payload["shots"], payload.get("purpose", "video_clip")
        if any(not isinstance(row, dict) or set(row) - {"shot_id", "prompt", "duration_ms", "params"} for row in shots):
            raise ResourceError("镜头输入字段不合法")
        ready = self.preview_shot_batch(project_id, dict(episode_id=payload.get("episode_id"),
            shot_ids=[row.get("shot_id") for row in shots], purpose=purpose))
        if ready["ready_count"] != ready["total"]:
            raise ResourceError("所选镜头仍有输入缺口，请先预览并补齐或缩小本批", "context_gaps")
        dependencies, jobs, history, offset = {}, [], [], 0
        while True:
            page = self.list_generation_jobs(project_id, offset=offset, limit=200)
            history.extend(page["items"])
            offset += len(page["items"])
            if offset >= page["total"] or not page["items"]:
                break
        for row in shots:
            context = self.compile_shot_context(project_id, row["shot_id"], purpose=purpose)
            if context["revision"] != ready["revision"]:
                raise Conflict("制作方案预览期间输入已改变")
            first = [item["media_id"] for item in context.get("media", []) if item["role"] == "first_frame"]
            if len(first) > 1:
                raise ResourceError("镜头存在多个首帧用途，请先明确当前输入", "first_frame_ambiguous")
            request = normalize_request(dict(row, modality="video", purpose=purpose,
                first_frame_media_id=first[0] if first else None), row["shot_id"], purpose, "video")
            request["context_sha256"] = context["sha256"]
            candidate = max([job["candidate_no"] for job in history
                if job.get("shot_id") == row["shot_id"] and job.get("purpose") == purpose] + [-1]) + 1
            jobs.append(dict(task_key=row["shot_id"] + ":" + purpose, model_id=payload.get("model_id"),
                candidate_no=candidate, request=request))
            dependencies.update({item["id"]: {"id": item["id"], "sha256": item["sha256"]}
                                 for item in context.get("artifacts", [])})
        document = dict(format="vsc.production-run/v1", project_id=project_id,
            scope=payload["episode_id"], approved_inputs=list(dependencies.values()),
            series_batch={"jobs": jobs}, execution_policy=payload["execution_policy"])
        from vsc.production.run_policy import authorization_policy
        for job in jobs:
            authorization_policy(document, None, job["request"],
                lambda identifier: self.get_artifact_version(project_id, identifier))
        quote = self.preview_generation_quote(project_id, {"document": document})
        if quote["revision"] != ready["revision"]:
            raise Conflict("制作方案报价期间输入已改变")
        document["generation_quote"] = quote["generation_quote"]
        document["operations"] = {item["operation"]: item["native_units"] for item in quote["generation_quote"]["jobs"]}
        from vsc.production.commerce_quote import attach_commerce_quote
        commerce=attach_commerce_quote(self,project_id,document,quote,payload)
        artifact = dict(artifact_type="production-run", stage="production",
            artifact_key="first-production:" + payload["episode_id"] + ":" + fingerprint(sorted(row["shot_id"] for row in shots))[:16],
            document=document, dependency_ids=sorted(dependencies), object_ids=[payload["episode_id"]])
        return dict(project_id=project_id, revision=ready["revision"], artifact=artifact,
            preview_sha256=fingerprint(artifact), generation_quote=quote["generation_quote"], commerce_quote=commerce, needs_approval=True)

    def propose_first_production(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if set(payload) != {"request", "preview_sha256"}:
            raise ResourceError("保存需要所预览的制作请求与摘要")
        return self.store.propose_first_production(project_id, payload,
            build_preview=self.preview_first_production, **kw)

    def get_production_episodes(self, project_id, *, offset=0, limit=100):
        from vsc.assets.resource_service import ResourceError
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ResourceError("集列表分页范围不合法")
        return self.store.get_production_episodes(project_id, offset=offset, limit=limit)

    def create_episode_batch(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        titles = payload.get("titles")
        if (set(payload) - {"titles", "parent_id"} or not isinstance(titles, list)
                or not 1 <= len(titles) <= 50 or any(not isinstance(t, str) or not t.strip()
                    or len(t) > 200 for t in titles)):
            raise ResourceError("请提供 1–50 个非空集名，每个不超过 200 字")
        return self._write("create_episode_batch", project_id, payload, **kw)

    def reorder_episodes(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        ids = payload.get("episode_ids")
        if (set(payload) != {"parent_id", "episode_ids"} or not isinstance(ids, list)
                or not ids or len(ids) > 1000 or any(not isinstance(i, str) for i in ids)):
            raise ResourceError("请提供所属部与完整集顺序")
        return self._write("reorder_episodes", project_id, payload, **kw)

    def preview_shot_batch(self, project_id, payload):
        from vsc.assets.resource_service import ResourceError, Conflict, context_digest
        if not isinstance(payload, dict) or set(payload) - {"episode_id", "shot_ids", "purpose"}:
            raise ResourceError("镜头预览参数不合法")
        ids = payload.get("shot_ids")
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 50
                or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids)):
            raise ResourceError("每批选择 1–50 个不同镜头")
        episode = payload.get("episode_id")
        tree = self.get_project_tree(project_id)
        nodes = {row["id"]: row for row in tree["nodes"]}
        if nodes.get(episode, {}).get("kind") != "episode":
            raise ResourceError("请选择已登记的集", "episode_required")
        revision, rows = tree["revision"], []
        for identifier in ids:
            node, visited = nodes.get(identifier), set()
            if not node or node.get("kind") != "shot":
                raise ResourceError("镜头不属于当前项目", "shot_scope_mismatch")
            cursor = node
            while cursor and cursor["id"] not in visited and cursor["id"] != episode:
                visited.add(cursor["id"])
                cursor = nodes.get(cursor.get("parent_id"))
            if not cursor or cursor["id"] != episode:
                raise ResourceError("本批不能包含其他集的镜头", "shot_scope_mismatch")
            context = self.compile_shot_context(project_id, identifier, purpose=payload.get("purpose", "video_clip"))
            if context["revision"] != revision:
                raise Conflict("预览期间输入已改变，请重新读取")
            rows.append(dict(shot_id=identifier, title=node.get("title"), ready=context["ready"],
                gaps=context.get("gaps", []), context_sha256=context.get("sha256") or context_digest(context),
                references=[{k: item.get(k) for k in ("media_id", "sha256", "role", "target_object_id")}
                    for item in context.get("media", [])]))
        if self.get_project(project_id)["revision"] != revision:
            raise Conflict("预览期间输入已改变，请重新读取")
        return dict(project_id=project_id, episode_id=episode, revision=revision, items=rows,
            ready_count=sum(row["ready"] for row in rows), total=len(rows))


class ProductionPlatform:
    def __init__(self, catalog):
        self.catalog = catalog

    def query(self, project_id, *, episode_id=None, offset=0, limit=24):
        from vsc.assets.workbench import Workbench
        from vsc.assets.resource_service import ResourceError, Conflict
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ResourceError("制作页面分页不合法")
        reader = self.catalog._reader(project_id)
        if reader is not None:
            tree = reader.tree()
            episodes = [n for n in tree["nodes"] if n["kind"] == "episode"]
            return dict(project_id=project_id, revision=reader.project()["revision"], read_only=True,
                episodes=dict(items=episodes, total=len(episodes), next_offset=None),
                message="旧项目保持原权威，可继续从专业入口阅读固定版本。")
        service, wb = self.catalog.service, Workbench(self.catalog)
        episodes = service.get_production_episodes(project_id, offset=offset, limit=limit)
        revision = episodes["revision"]
        data = dict(project_id=project_id, revision=revision, read_only=False, episodes=episodes)
        if episode_id:
            overview = wb.query(project_id, object_id=episode_id, section="shots", revision=revision, limit=100)
            if overview["scope"]["kind"] != "episode":
                raise ResourceError("制作页面需要明确的集范围", "episode_required")
            data.update(episode=overview["scope"], shots=overview["sections"]["shots"])
            for section in ("jobs", "renders", "versions"):
                page = wb.query(project_id, object_id=episode_id, section=section, revision=revision, limit=100)
                data[section] = page["sections"][section]
            requirements = service.get_resource_requirements(project_id, object_id=episode_id)
            if requirements["revision"] != revision:
                raise Conflict("制作投影读取期间已改变，请刷新")
            data["requirements"] = requirements
        return data
