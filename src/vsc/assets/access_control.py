"""Request identity is independent of the original actor audit label."""
from __future__ import annotations
from contextvars import ContextVar
from dataclasses import dataclass,replace
from hashlib import sha256
from datetime import datetime,timezone
import re

@dataclass(frozen=True)
class Principal:
    identity_id:str|None=None
    actor:str|None=None
    local:bool=False
    local_read:bool=False
    api_key_id:str|None=None
    credential_id:str|None=None
    share_id:str|None=None
    workspace_id:str|None=None

_request_principal=ContextVar('vsc_request_principal',default=None)
def current_principal():return _request_principal.get()
def set_principal(value):return _request_principal.set(value)
def reset_principal(token):_request_principal.reset(token)
def denied(message='当前身份没有此操作权限'):raise ResourceError(message,'access_denied',403)
def secret_hash(secret):
    if not isinstance(secret,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,200}',secret):raise ResourceError('凭据格式无效','invalid_access_secret',403)
    return sha256(secret.encode()).hexdigest()
def label(value,maximum=200):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or '\x00' in value:raise ResourceError('名称为空或过长','invalid_access_input')
    return value.strip()
def expires(value):
    try:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,AttributeError):raise ResourceError('有效期需要带时区的时间','invalid_expiry')
    if parsed.tzinfo is None or parsed<=datetime.now(timezone.utc):raise ResourceError('有效期已经结束或缺少时区','invalid_expiry')
    return parsed

CAPABILITIES={'owner':{'read','edit','review','approve','execute','manage','publish'},'editor':{'read','edit','execute'},'reviewer':{'read','review'},'viewer':{'read'}}
MANAGE_ACTIONS={'community_rule_save','community_moderate','distribution_channel_save','management_rename','management_edit','management_trash','management_restore','management_purge','management_retention','service_operations_configure','service_announcement_publish','service_request_process','access_assign_project','access_member','access_review_policy','commerce_configure_plan','commerce_configure_campaign','commerce_allocate','commerce_reclaim'}
REVIEW_ACTIONS={'record_review','add_script_note','add_artifact_review_note','access_review_commit','access_review_batch_commit','create_role_dispatch'}
APPROVE_ACTIONS={'decide_artifact','select_candidate','reject_candidate','retire_binding','decide_rights','decide_script_note','decide_script_suggestion'}
EXECUTE_ACTIONS={'start_prompt_assist','start_provider_asset_registration','finish_provider_asset_registration','claim_spatial_export','finish_spatial_export','cancel_spatial_export','cancel_edit_export','start_creative_lyrics','analyze_creative_music','claim_spatial_plan_task','service_api_cancel','execute_canvas_agent_turn','execute_intelligent_task','create_generation_job','enqueue_local_production','run_text_tool','start_text_tool_attempt','create_edit_render','request_edit_export','create_preview_job','process_creative_tool_local'}
PUBLISH_ACTIONS={'community_publication_state','distribution_prepare','distribution_submit','distribution_receipt','publish_canvas_template','create_creative_canvas_template','publish_creative_canvas_template','access_share','library_publish'}
def action_capability(action):
    if action in {'copy_direct_canvas', 'set_canvas_collaboration', 'recover_canvas_batch'}:return 'edit'
    if action == 'start_marketing_canvas':return 'execute'
    if action in {'generate_intelligent_work_batch','advance_intelligent_work_batch'}:return 'execute'
    if action == "community_report":return "read"
    if action=='commerce_workspace_transfer':return 'manage'
    if action in {'generate_workbench', 'generate_canvas_work'}:return 'execute'
    if action in {'service_request_create','service_request_withdraw','service_export_build','service_api_key_issue','service_api_key_revoke','service_account_close'}:return 'read'
    if action in MANAGE_ACTIONS:return 'manage'
    if action in REVIEW_ACTIONS:return 'review'
    if action in APPROVE_ACTIONS:return 'approve'
    if action in EXECUTE_ACTIONS:return 'execute'
    if action in PUBLISH_ACTIONS:return 'publish'
    return 'edit'

class AccessControlServiceMixin:
    def authorize_access(self,project_id,capability='read',target_type=None,target_id=None):
        return self.store.authorize_access(project_id,capability,target_type=target_type,target_id=target_id)
    def authorize_workspace(self,workspace_id,capability='manage'):return self.store.authorize_workspace(workspace_id,capability)
    def commerce_validate_member(self,project_id,target_actor):return self.store.access_member_valid(project_id,target_actor)
    def access_scope(self,project_id):return self.authorize_access(project_id)
    def access_snapshot(self):return self.store.access_snapshot()
    def access_workspace_resources(self,workspace_id,*,offset=0,limit=24,query=''):
        if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=100 or not isinstance(query,str) or len(query)>200:raise ResourceError('分页或检索条件无效','invalid_access_input')
        return self.store.access_workspace_resources(workspace_id,offset=offset,limit=limit,query=query.strip())
    def access_command(self,action,payload,*,expected_revision,idempotency_key,actor):
        if not isinstance(payload,dict) or type(expected_revision)is not int or expected_revision<0 or not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=200:raise ResourceError('需要固定权限版本和操作标识','invalid_access_input')
        return self.store.access_command(action,payload,expected_revision=expected_revision,idempotency_key=idempotency_key,actor=actor)
    def ensure_local_access(self,actor):return self.store.ensure_local_access(label(actor))
    def authenticate_access(self,secret):return self.store.authenticate_access(secret)
    def access_invitation_preview(self,secret):return self.store.access_invitation_preview(secret)
    def accept_access_invitation(self,payload,*,include_target=False):return self.store.accept_access_invitation(payload,include_target=include_target)
    def access_share_view(self):return self.store.access_share_view()
    def access_migration_preview(self,project_id,workspace_id):return self.store.access_migration_preview(project_id,workspace_id)
    def access_member_removal_preview(self,workspace_id,identity_id):return self.store.access_member_removal_preview(workspace_id,identity_id)
    def get_user_preferences(self):return self.store.get_user_preferences()
    def update_user_preferences(self,payload,*,actor=None):return self.store.update_user_preferences(payload,actor=actor)

from vsc.assets.resource_service import ResourceError,Conflict
