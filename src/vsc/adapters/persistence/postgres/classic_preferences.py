"""Personal favorites and immutable prompt requests reuse the original authorities."""
import hashlib
import json
from sqlalchemy import select, insert, update
from vsc.assets.resource_service import ResourceError, Conflict
from vsc.assets.classic_production import DRAFT_TYPE
from . import schema as S
from .values import checked_id, new_id, clean, digest, CURRENT_REVISION

REQUEST_TYPE = 'classic-prompt-request'
RESULT_TYPE = 'classic-prompt-result'


def favorite_identity(store, conn, actor=None, required=False):
    from vsc.assets.access_control import denied
    principal, person, _ = store._access_principal(conn)
    valid = bool(person and person['active'] and principal and not principal.share_id and not principal.api_key_id)
    if required and (not valid or person['actor'] != actor):
        denied('收藏需要当前已登录成员身份')
    return person['id'] if valid else None


def local_media_predicate(project_id):
    from sqlalchemy import and_, exists
    source = exists(select(S.media_sources.c.id).join(S.source_versions, and_(
        S.source_versions.c.project_id == S.media_sources.c.project_id,
        S.source_versions.c.id == S.media_sources.c.source_id)).where(
        S.media_sources.c.project_id == project_id, S.media_sources.c.media_id == S.media_items.c.id,
        S.source_versions.c.kind.in_(['user_upload', 'file-import'])))
    generated = exists(select(S.job_outputs.c.id).where(S.job_outputs.c.project_id == project_id,
        S.job_outputs.c.media_id == S.media_items.c.id))
    return source & ~generated


class ClassicPreferencesRepository:
    def favorite_classic_media(self, p, payload, *, actor, idempotency_key, expected_revision):
        from .access_control import authority_lock
        with self.engine.begin() as conn:
            authority_lock(conn, True)
            self._access_require(conn, p, 'read')
            identity = favorite_identity(self, conn, actor, True)
            key = identity + ':classic-favorite:' + idempotency_key
            request_sha = digest({'action': 'favorite_classic_media', 'project_id': p, 'payload': payload})
            receipt = conn.execute(select(S.access_commands).where(S.access_commands.c.key == key)).mappings().first()
            if receipt:
                if receipt['request_sha256'] != request_sha:
                    raise Conflict('收藏操作标识已用于不同请求', 'idempotency_conflict')
                return clean(receipt['response'])
            media_id = checked_id(payload['media_id'])
            media = conn.execute(self._media_query(p).where(S.media_items.c.id == media_id)).mappings().first()
            if not media:
                raise ResourceError('收藏媒体不在当前可读项目内', 'not_found', 404)
            table = S.classic_media_favorites
            where = (table.c.project_id == p) & (table.c.identity_id == identity) & (table.c.media_id == media_id)
            prior = conn.execute(select(table).where(where).with_for_update()).mappings().first()
            version = prior['version'] if prior else 0
            if payload['base_version'] != version:
                raise Conflict('另一页面已修改此收藏，请刷新后再操作', 'classic_favorite_conflict')
            values = dict(active=payload['active'], version=version + 1)
            if prior:
                conn.execute(update(table).where(where).values(**values))
            else:
                conn.execute(insert(table).values(project_id=p, id=new_id(), identity_id=identity, media_id=media_id, **values))
            return self._access_event(conn, key, identity, 'favorite_classic_media', request_sha,
                self._access_state(conn), dict(media_id=media_id, **values))

    def start_prompt_assist(self, p, payload, *, claim, actor, **kw):
        from vsc.bootstrap import repository_root
        from vsc.project.role_runtime import bind_packet
        def work(conn, project):
            draft = self._one(conn, S.artifact_versions, p, checked_id(payload['draft_version_id']))
            if draft['artifact_type'] != DRAFT_TYPE or draft['sha256'] != payload['draft_sha256']:
                raise Conflict('提示词来源不是所见固定制作稿', 'prompt_assist_draft_changed')
            doc = json.loads(draft['document'])
            prompt = doc.get('performance_prompt', '') if doc['mode'] == 'digital_human' else doc['prompt']
            refs = []
            if payload['include_references']:
                for ref in doc['references']:
                    media = self._one(conn, S.media_items, p, ref['media_id'])
                    if media['modality'] == 'image':
                        refs.append({'id': ref['media_id'], 'sha256': ref['sha256']})
            if len(refs) > 8:
                raise ResourceError('助手每次最多理解8张固定参考图', 'prompt_assist_reference_limit')
            if payload['operation'] == 'recognize' and not refs:
                raise ResourceError('智能识别需要打开智能引用并添加参考图', 'prompt_assist_image_required')
            if payload['operation'] != 'recognize' and not prompt.strip():
                raise ResourceError('先填写提示词', 'prompt_assist_prompt_required')
            identifier = new_id()
            skill_sha = hashlib.sha256((repository_root()/'skills/vsc-direct/SKILL.md').read_bytes()).hexdigest()
            packet = bind_packet({'context_id': 'prompt-'+identifier, 'project': {'project_id': p},
                'revision': project['revision'], 'role': self._role('director'), 'task': '提出提示词建议：'+payload['operation'],
                'inputs': [], 'approved_memories': [], 'scope': doc['shot_id'], 'parent_brief': None,
                'rules': ['固定输入仅为工作稿；输出是建议，用户显式应用，不自动批准或生成。']},
                host='grok-build-prompt-assist', actor=actor, ownership=[])
            internal = dict(actor=actor, expected_revision=project['revision'], idempotency_key='prompt-internal', _transaction=(conn, project))
            dispatch = self.create_role_dispatch(p, {'packet': packet}, **internal)
            self.consume_role_dispatch(p, dict(dispatch_id=dispatch['dispatch_id'], instance_id=packet['dispatch']['instance_id'],
                role_id='director', context_sha256=packet['context_sha256'], packet=packet), **internal)
            document = dict(payload, prompt=prompt, reference_images=refs, shot_id=doc['shot_id'], mode=doc['mode'],
                dispatch_id=dispatch['dispatch_id'], skill_sha256=skill_sha, created_by=actor)
            artifact = self._create_artifact(conn, project, dict(id=identifier, artifact_key='prompt-request:'+identifier,
                artifact_type=REQUEST_TYPE, document=document, object_ids=[doc['shot_id']], dependency_ids=[draft['id']]))
            claim['created'] = True
            return {'id': artifact['id'], 'sha256': artifact['sha256']}
        return self._mutate(p, 'start_prompt_assist', payload, actor=actor, callback=work, **kw)

    def get_prompt_assist(self, p, identifier):
        with self.engine.connect() as conn:
            project = self._project(conn, p)
            row = self._one(conn, S.artifact_versions, p, checked_id(identifier))
            if row['artifact_type'] != REQUEST_TYPE:
                raise ResourceError('请求不属于提示词助手', 'prompt_assist_scope')
            result = conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id == p,
                S.artifact_versions.c.artifact_key == 'prompt-result:'+identifier)).mappings().first()
            value = json.loads(result['document']) if result else {'status': 'submission_unknown', 'result': None, 'error': 'prompt_assist_receipt_pending'}
            if result and (result['artifact_type'] != RESULT_TYPE or value.pop('request_sha256', None) != row['sha256']):
                raise Conflict('助手结果与原请求摘要不符', 'prompt_assist_source_changed')
            return clean(dict(id=identifier, request=json.loads(row['document']), request_sha256=row['sha256'],
                result_artifact_id=result['id'] if result else None, revision=project['revision'], **value))

    def finish_prompt_assist(self, p, identifier, result, error, *, actor):
        def work(conn, project):
            request = self._one(conn, S.artifact_versions, p, identifier)
            if request['artifact_type'] != REQUEST_TYPE:
                raise ResourceError('请求不属于提示词助手')
            source = json.loads(request['document'])
            status = 'completed' if result is not None else 'submission_unknown' if error == 'prompt_assist_submission_unknown' else 'failed'
            artifact = self._create_artifact(conn, project, dict(artifact_key='prompt-result:'+identifier, artifact_type=RESULT_TYPE,
                document=dict(status=status, result=result, error=error, request_sha256=request['sha256']),
                object_ids=[source['shot_id']], dependency_ids=[request['id']]))
            dispatch = self._one(conn, S.role_dispatches, p, source['dispatch_id'])
            packet = dispatch['packet']
            if isinstance(packet, str): packet = json.loads(packet)
            d = packet['dispatch']
            returned = dict(role_id=d['role_id'], role_sha256=d['role_sha256'], context_id=packet['context_id'],
                context_sha256=packet['context_sha256'], dispatch_id=d['id'], instance_id=d['instance_id'],
                result_refs=[dict(kind='artifact', id=artifact['id'], sha256=artifact['sha256'])], memory_proposals=[])
            self.return_role_dispatch(p, dict(dispatch_id=d['id'], instance_id=d['instance_id'], role_id=d['role_id'],
                context_sha256=packet['context_sha256'], result=returned, return_key='prompt:'+identifier, closed=True),
                actor=source['created_by'], expected_revision=project['revision'], idempotency_key='prompt-return', _transaction=(conn, project))
            return {'id': artifact['id']}
        return self._mutate(p, 'finish_prompt_assist', {'request_id': identifier, 'result': result, 'error': error},
            actor=actor, expected_revision=CURRENT_REVISION, idempotency_key='prompt-result:'+identifier, callback=work)
