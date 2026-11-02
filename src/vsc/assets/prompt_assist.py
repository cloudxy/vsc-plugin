"""Explicit prompt suggestions; no generation, approval, or automatic draft replacement."""
import hashlib
import json
from vsc.assets.resource_service import ResourceError


class PromptAssistServiceMixin:
    def favorite_classic_media(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if (set(payload) != {'media_id', 'active', 'base_version'} or type(payload['active']) is not bool
                or type(payload['base_version']) is not int or payload['base_version'] < 0):
            raise ResourceError('收藏需要媒体、明确状态与当前个人版本', 'invalid_classic_favorite')
        return self.store.favorite_classic_media(project_id, payload, **kw)

    def get_prompt_assist(self, project_id, request_id):
        self.authorize_access(project_id, 'read')
        return self.store.get_prompt_assist(project_id, request_id)

    def start_prompt_assist(self, project_id, payload, **kw):
        from vsc.production.prompt_assist import GrokBuildPromptAssistant, OPERATIONS, LANGUAGES, validate_result
        from vsc.production.spatial_planner import reference_blocks
        from vsc.bootstrap import repository_root
        self._validate_write(payload, **kw)
        self.authorize_access(project_id, 'execute')
        if (set(payload) != {'draft_version_id', 'draft_sha256', 'operation', 'target_language', 'include_references'}
                or payload['operation'] not in OPERATIONS or payload['target_language'] not in LANGUAGES
                or type(payload['include_references']) is not bool):
            raise ResourceError('提示词助手需要固定稿、操作和语言', 'invalid_prompt_assist_request')
        claim = {'created': False}
        request = self.store.start_prompt_assist(project_id, payload, claim=claim, **kw)
        if claim['created']:
            result = error = None
            try:
                fixed = self.store.get_prompt_assist(project_id, request['id'])
                source = dict(fixed['request'])
                skill = (repository_root() / 'skills/vsc-direct/SKILL.md').read_text(encoding='utf8')
                if hashlib.sha256(skill.encode()).hexdigest() != source['skill_sha256']:
                    raise ResourceError('固定助手规范已改变', 'prompt_assist_skill_changed')
                packet = self.get_role_dispatch(project_id, source['dispatch_id'])['packet']
                try:
                    manifest = json.loads((packet.get('parent_brief') or {}).get('content','{}')).get('role_materials_manifest')
                except (TypeError,ValueError,AttributeError) as failure:
                    raise ResourceError('原提示词请求缺少固定专业材料清单','role_materials_missing') from failure
                if not isinstance(manifest,dict):
                    raise ResourceError('原提示词请求缺少固定专业材料清单','role_materials_missing')
                from vsc.production.role_materials import compile_role_materials
                source['_materials'] = compile_role_materials('director','vsc-direct','prompt-'+source['operation'],
                    method_ids=manifest.get('method_ids',()),expected_manifest=manifest)
                blocks = reference_blocks(self, project_id, {'reference_media': source['reference_images']})
                backend = getattr(self, 'prompt_assistant', None) or GrokBuildPromptAssistant()
                if not backend.available():
                    raise ResourceError('本机提示词助手尚未接通 Grok Build', 'prompt_assist_host_unavailable', 503)
                result = validate_result(backend.generate(packet, source, skill, blocks))
            except ResourceError as failure:
                error = failure.code
            except Exception:
                error = 'prompt_assist_submission_unknown'
            self.store.finish_prompt_assist(project_id, request['id'], result, error, actor=kw['actor'])
        return self.get_prompt_assist(project_id, request['id'])
