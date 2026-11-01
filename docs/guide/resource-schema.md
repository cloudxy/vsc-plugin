# PostgreSQL 资源表字典

由 `scripts/project/schema.py describe` 生成；表定义与迁移是规范。

| 表 | 一行的键／粒度 | 关系外键 |
| --- | --- | --- |
| access_identities | id |  |
| access_state | id |  |
| asset_categories | code | parent_code → asset_categories |
| library_entries | id | id,current_version_id → library_entry_versions |
| media_blobs | id |  |
| projects | id |  |
| providers | id |  |
| access_commands | key | identity_id → access_identities |
| access_credentials | id | identity_id → access_identities |
| access_workspaces | id | created_by → access_identities; parent_id → access_workspaces |
| artifact_versions | project_id, id | project_id → projects; project_id,supersedes_id → artifact_versions |
| blob_locations | id | blob_id → media_blobs |
| budget_limit_versions | project_id, revision, unit | project_id → projects |
| command_receipts | project_id, idempotency_key | project_id → projects |
| commerce_campaigns | project_id, id | project_id → projects |
| commerce_plan_versions | project_id, id | project_id → projects |
| creative_objects | project_id, id | project_id → projects |
| library_entry_decisions | id | entry_id → library_entries |
| library_entry_versions | id | entry_id → library_entries |
| management_folders | project_id, id | project_id → projects; project_id,parent_id → management_folders |
| management_project_states | project_id, id | project_id → projects |
| management_retention | project_id, id | project_id → projects |
| media_items | project_id, id | blob_id → media_blobs; project_id → projects |
| media_operations | project_id, id | project_id → projects |
| parse_jobs | project_id, id | project_id → projects |
| project_revisions | project_id, revision | project_id → projects |
| provider_models | id | provider_id → providers |
| script_suggestions | project_id, id | project_id → projects |
| service_announcements | project_id, id | created_by → access_identities; project_id → projects |
| service_api_keys | project_id, id | identity_id → access_identities; project_id → projects |
| service_configuration_versions | project_id, id | created_by → access_identities; project_id → projects |
| source_versions | project_id, id | project_id → projects |
| access_projects | project_id | assigned_by → access_identities; project_id → projects; workspace_id → access_workspaces |
| access_workspace_members | workspace_id, identity_id | identity_id → access_identities; workspace_id → access_workspaces |
| artifact_category_links | project_id, artifact_id, category_code | category_code → asset_categories; project_id,artifact_id → artifact_versions |
| artifact_decisions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions |
| artifact_dependencies | project_id, artifact_id, dependency_id | project_id,artifact_id → artifact_versions; project_id,dependency_id → artifact_versions |
| artifact_object_scopes | project_id, artifact_id, object_id | project_id,artifact_id → artifact_versions; project_id,object_id → creative_objects |
| asset_identities | project_id, id | project_id → projects; project_id,id,object_kind → creative_objects |
| commerce_orders | project_id, id | project_id → projects; project_id,plan_id → commerce_plan_versions; project_id,renewal_of_order_id → commerce_orders |
| commerce_rates | project_id, id | model_id → provider_models; project_id → projects; project_id,plan_id → commerce_plan_versions |
| commerce_settings | project_id, id | project_id → projects; project_id,price_version_id → commerce_plan_versions |
| intelligent_definitions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions |
| library_catalog_edits | id | entry_id,library_version_id → library_entry_versions; workspace_id → access_workspaces |
| library_version_media | library_version_id, member_key | blob_id → media_blobs; library_version_id → library_entry_versions |
| management_object_states | project_id, id | project_id → projects; project_id,object_id → creative_objects |
| media_category_links | project_id, media_id, category_code | category_code → asset_categories; project_id,media_id → media_items |
| media_checks | project_id, id | blob_id,blob_sha256 → media_blobs; project_id → projects; project_id,media_id → media_items; project_id,media_id,blob_id → media_items; project_id,project_revision → project_revisions |
| media_folder_memberships | project_id, id | project_id → projects; project_id,folder_id → management_folders; project_id,media_id → media_items |
| media_lifecycle_decisions | project_id, id | project_id → projects; project_id,media_id → media_items |
| media_renditions | project_id, id | blob_id → media_blobs; project_id → projects; project_id,media_id → media_items; project_id,media_id,source_blob_id → media_items; source_blob_id,source_sha256 → media_blobs |
| media_sources | project_id, id | project_id → projects; project_id,media_id → media_items; project_id,source_id → source_versions |
| method_evaluations | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,baseline_media_id → media_items; project_id,criteria_artifact_id → artifact_versions; project_id,method_artifact_id → artifact_versions; project_id,output_media_id → media_items; project_id,trial_run_id → artifact_versions |
| object_folder_memberships | project_id, id | project_id → projects; project_id,folder_id → management_folders; project_id,object_id → creative_objects |
| operation_inputs | project_id, id | project_id → projects; project_id,media_id → media_items; project_id,operation_id → media_operations; project_id,operation_id,mask_input_id → operation_inputs |
| operation_outputs | project_id, id | project_id → projects; project_id,media_id → media_items; project_id,operation_id → media_operations |
| parse_attempts | project_id, id | project_id → projects; project_id,job_id → parse_jobs |
| parse_job_inputs | project_id, id | project_id → projects; project_id,job_id → parse_jobs; project_id,source_id → source_versions; project_id,source_id,source_sha256 → source_versions |
| preview_jobs | project_id, id | project_id → projects; project_id,media_id → media_items |
| provider_configurations | provider_id | previous_model_id → provider_models; provider_id → providers |
| provider_routes | id | fallback_provider → providers; preferred_model_id,preferred_provider,preferred_model_version,modality → provider_models; preferred_provider → providers |
| rights_decisions | project_id, id | project_id → projects; project_id,media_id → media_items; project_id,source_id → source_versions |
| role_dispatches | project_id, id | project_id → projects; project_id,scope_object_id → creative_objects |
| script_drafts | project_id, id | project_id → projects; project_id,base_artifact_id → artifact_versions; project_id,submitted_artifact_id → artifact_versions |
| script_notes | project_id, id | project_id → projects; project_id,base_artifact_id → artifact_versions |
| script_suggestion_decisions | project_id, id | project_id → projects; project_id,suggestion_id → script_suggestions |
| service_api_calls | project_id, id | project_id → projects; project_id,api_key_id → service_api_keys; project_id,run_version_id → artifact_versions |
| service_requests | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,media_id → media_items; requester_id → access_identities |
| source_intake_documents | project_id, source_id | project_id,source_id → source_versions |
| works | project_id, id | project_id → projects; project_id,id,object_kind → creative_objects |
| access_invitations | id | accepted_by → access_identities; created_by → access_identities; project_id → access_projects; workspace_id → access_workspaces |
| access_project_members | project_id, identity_id | identity_id → access_identities; project_id → access_projects |
| asset_spec_versions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,asset_id → asset_identities |
| commerce_buckets | project_id, id | project_id → projects; project_id,order_id → commerce_orders; project_id,parent_bucket_id → commerce_buckets |
| commerce_invoices | project_id, id | project_id → projects; project_id,order_id → commerce_orders |
| commerce_payment_events | project_id, id | project_id → projects; project_id,order_id → commerce_orders |
| current_artifact_versions | project_id, artifact_key | project_id,artifact_id,decision_id → artifact_decisions; project_id,artifact_key,artifact_id → artifact_versions |
| dispatch_consumptions | project_id, id | project_id → projects; project_id,dispatch_id → role_dispatches |
| dispatch_inputs | project_id, dispatch_id, artifact_id | project_id,artifact_id → artifact_versions; project_id,dispatch_id → role_dispatches |
| dispatch_returns | project_id, id | project_id → projects; project_id,dispatch_id → role_dispatches |
| dispatch_sources | project_id, dispatch_id, source_id | project_id,dispatch_id → role_dispatches; project_id,source_id → source_versions |
| episodes | project_id, id | project_id → projects; project_id,id,object_kind → creative_objects; project_id,parent_id → works |
| identity_category_links | project_id, asset_id, category_code | category_code → asset_categories; project_id,asset_id → asset_identities |
| library_cart_items | id | library_version_id,member_key → library_version_media |
| library_catalog_tags | edit_id, tag | edit_id → library_catalog_edits |
| library_download_requests | id | library_version_id,member_key → library_version_media |
| library_reuses | project_id, id | library_version_id,member_key,blob_id → library_version_media; project_id → projects; project_id,media_id → media_items; project_id,media_id,blob_id → media_items; project_id,rights_decision_id → rights_decisions; project_id,source_id → source_versions |
| media_recycle_actions | project_id, id | project_id → projects; project_id,decision_id → media_lifecycle_decisions; project_id,media_id → media_items; project_id,media_id,decision_id → media_lifecycle_decisions |
| role_memories | project_id, id | project_id → projects; project_id,producer_dispatch_id → role_dispatches; project_id,scope_object_id → creative_objects |
| script_note_anchors | project_id, note_id | project_id,note_id → script_notes |
| script_note_decisions | project_id, id | project_id → projects; project_id,note_id → script_notes |
| script_suggestion_runs | project_id, id | project_id → projects; project_id,draft_id → script_drafts |
| service_export_files | project_id, id | project_id → projects; project_id,request_id → service_requests; project_id,request_id,requester_id → service_requests; requester_id → access_identities |
| service_request_events | project_id, id | created_by → access_identities; project_id → projects; project_id,request_id → service_requests |
| source_extractions | project_id, id | project_id → projects; project_id,attempt_id → parse_attempts; project_id,source_id → source_versions; project_id,source_id,source_sha256 → source_versions |
| voice_spec_versions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,reference_media_id → media_items; project_id,voice_id → asset_identities |
| artifact_asset_spec_refs | project_id, artifact_id, asset_id | project_id,artifact_id → artifact_versions; project_id,asset_id,spec_version_id → asset_spec_versions |
| character_voice_bindings | project_id, id | project_id → projects; project_id,character_id → asset_identities; project_id,scope_version_id → artifact_versions; project_id,voice_spec_id → voice_spec_versions |
| commerce_redemptions | project_id, id | project_id → projects; project_id,bucket_id → commerce_buckets; project_id,campaign_id → commerce_campaigns |
| creative_canvases | project_id, id | project_id → projects; project_id,episode_id → episodes; project_id,id,current_version_id → creative_canvas_versions |
| creative_tool_imports | project_id, id | blob_id,sha256 → media_blobs; project_id → projects; project_id,episode_id → episodes; project_id,media_id,blob_id → media_items; source_project_id,source_artifact_id → artifact_versions; source_project_id,source_media_id,blob_id → media_items |
| dispatch_result_artifacts | project_id, return_id, artifact_id | project_id,artifact_id → artifact_versions; project_id,return_id → dispatch_returns |
| edit_workspaces | project_id, id | project_id → projects; project_id,episode_id → episodes; project_id,id,current_version_id → edit_revisions |
| intelligent_workflows | project_id, id | project_id → projects; project_id,definition_id → intelligent_definitions; project_id,episode_id → episodes |
| media_import_batches | project_id, id | project_id → projects; project_id,episode_id → episodes |
| role_memory_versions | project_id, id | project_id → projects; project_id,memory_id → role_memories; project_id,producer_dispatch_id → role_dispatches |
| scenes | project_id, id | project_id → projects; project_id,id,object_kind → creative_objects; project_id,parent_id → episodes |
| script_run_suggestions | project_id, run_id, suggestion_id | project_id,run_id → script_suggestion_runs; project_id,suggestion_id → script_suggestions |
| source_anchors | project_id, id | project_id → projects; project_id,extraction_id → source_extractions; project_id,extraction_id,source_id → source_extractions; project_id,source_id → source_versions |
| text_tool_units | project_id, id | project_id → projects; project_id,current_version_id → artifact_versions; project_id,episode_id → episodes |
| timeline_versions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,episode_id → episodes |
| canvas_agent_sessions | project_id, id | project_id → projects; project_id,canvas_id → creative_canvases |
| creative_canvas_versions | project_id, id | project_id → projects; project_id,canvas_id → creative_canvases; project_id,canvas_id,parent_version_id → creative_canvas_versions |
| draft_source_refs | project_id, id | project_id → projects; project_id,anchor_id → source_anchors; project_id,draft_id → script_drafts |
| edit_revisions | project_id, id | project_id → projects; project_id,workspace_id → edit_workspaces |
| intelligent_versions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,source_artifact_id → artifact_versions; project_id,template_artifact_id → artifact_versions; project_id,workflow_id → intelligent_workflows; project_id,workflow_id,parent_id → intelligent_versions |
| media_import_items | project_id, id | project_id → projects; project_id,asset_id → asset_identities; project_id,batch_id → media_import_batches; project_id,media_id → media_items |
| render_versions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,style_version_id → artifact_versions; project_id,subtitle_version_id → artifact_versions; project_id,timeline_id → timeline_versions |
| role_memory_artifacts | project_id, memory_version_id, artifact_id | project_id,artifact_id,source_sha256 → artifact_versions; project_id,memory_version_id → role_memory_versions |
| role_memory_decisions | project_id, id | project_id → projects; project_id,memory_version_id,content_sha256 → role_memory_versions |
| role_memory_sources | project_id, memory_version_id, source_id | project_id,memory_version_id → role_memory_versions; project_id,source_id,source_sha256 → source_versions |
| role_memory_targets | project_id, memory_version_id, object_id | project_id,memory_version_id → role_memory_versions; project_id,object_id → creative_objects |
| script_lines | project_id, id | project_id → projects; project_id,scene_id → scenes; project_id,script_version_id → artifact_versions; project_id,script_version_id,source_sha256 → artifact_versions; project_id,speaker_id → asset_identities |
| sequences | project_id, id | project_id → projects; project_id,id,object_kind → creative_objects; project_id,parent_id → scenes |
| shot_design_units | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,artifact_id,source_sha256 → artifact_versions; project_id,scene_id → scenes |
| spatial_scenes | project_id, id | project_id → projects; project_id,episode_id → episodes; project_id,id,current_version_id → spatial_scene_versions; project_id,scene_id → scenes |
| text_tool_attempts | project_id, id | project_id → projects; project_id,input_version_id → artifact_versions; project_id,result_version_id → artifact_versions; project_id,unit_id → text_tool_units |
| text_tool_copies | project_id, id | project_id → projects; project_id,unit_id → text_tool_units; project_id,version_id → artifact_versions; source_project_id,source_version_id → artifact_versions |
| access_shares | id | created_by → access_identities; project_id → projects; project_id,canvas_id → creative_canvases; project_id,canvas_id,canvas_version_id → creative_canvas_versions |
| canvas_templates | project_id, id | project_id → projects; project_id,version_id → creative_canvas_versions |
| dispatch_memory_refs | project_id, dispatch_id, memory_version_id | project_id,decision_id,memory_version_id → role_memory_decisions; project_id,dispatch_id → role_dispatches; project_id,memory_version_id → role_memory_versions |
| edit_render_jobs | project_id, id | output_blob_id,output_sha256 → media_blobs; project_id → projects; project_id,edit_version_id → edit_revisions |
| edit_timeline_handoffs | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,edit_version_id → edit_revisions |
| execution_instances | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,line_id → script_lines; project_id,method_artifact_id → artifact_versions; project_id,voice_spec_id → voice_spec_versions |
| intelligent_assets | project_id, version_id, asset_key | project_id → projects; project_id,asset_id → asset_identities; project_id,spec_id → asset_spec_versions; project_id,version_id → intelligent_versions |
| intelligent_tasks | project_id, id | project_id → projects; project_id,dispatch_id → role_dispatches; project_id,output_version_id → intelligent_versions; project_id,plan_artifact_id → artifact_versions; project_id,version_id → intelligent_versions |
| render_caption_inputs | project_id, id | blob_id,blob_sha256 → media_blobs; project_id → projects; project_id,media_id → media_items; project_id,media_id,blob_id → media_items; project_id,render_id → render_versions |
| render_outputs | project_id, id | project_id → projects; project_id,media_id → media_items; project_id,render_id → render_versions |
| script_line_dispositions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,line_id → script_lines |
| script_line_sources | project_id, id | project_id → projects; project_id,anchor_id → source_anchors; project_id,line_id → script_lines |
| shot_design_line_refs | project_id, design_unit_id, line_id | project_id,design_unit_id → shot_design_units; project_id,line_id → script_lines |
| shot_design_panels | project_id, id | project_id → projects; project_id,design_unit_id → shot_design_units; project_id,media_id → media_items |
| shots | project_id, id | project_id → projects; project_id,id,object_kind → creative_objects; project_id,parent_id → sequences |
| spatial_scene_versions | project_id, id | project_id → projects; project_id,spatial_scene_id → spatial_scenes |
| text_tool_receipts | project_id, id | project_id → projects; project_id,attempt_id → text_tool_attempts |
| access_share_media | project_id, share_id, media_id | project_id,media_id → media_items; project_id,share_id → access_shares |
| canvas_template_copies | project_id, id | project_id → projects; project_id,canvas_id → creative_canvases; source_project_id,template_id → canvas_templates |
| canvas_template_favorites | project_id, template_id, actor | project_id → projects; project_id,template_id → canvas_templates |
| edit_revision_media | project_id, id | blob_id,blob_sha256 → media_blobs; project_id → projects; project_id,edit_version_id → edit_revisions; project_id,media_id → media_items; project_id,media_id,blob_id → media_items; project_id,shot_id → shots |
| execution_materials | project_id, id | project_id → projects; project_id,execution_id → execution_instances; project_id,media_id → media_items |
| execution_shots | project_id, id | project_id → projects; project_id,execution_id → execution_instances; project_id,shot_id → shots |
| generation_jobs | project_id, id | model_id → provider_models; model_id,provider_id,model_version,modality → provider_models; project_id → projects; project_id,asset_id → asset_identities; project_id,run_version_id → artifact_versions; project_id,shot_id → shots; provider_id → providers |
| intelligent_asset_runs | project_id, version_id, asset_key, run_artifact_id | project_id → projects; project_id,run_artifact_id → artifact_versions; project_id,version_id,asset_key → intelligent_assets |
| intelligent_decisions | project_id, id | project_id → projects; project_id,task_id → intelligent_tasks |
| intelligent_units | project_id, version_id, unit_key | project_id → projects; project_id,shot_id → shots; project_id,spatial_version_id → spatial_scene_versions; project_id,version_id → intelligent_versions |
| scene_location_refs | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,artifact_id,source_sha256 → artifact_versions; project_id,location_id → asset_identities; project_id,location_id,spec_version_id → asset_spec_versions; project_id,scene_id → scenes; project_id,shot_id → shots; project_id,spec_version_id → asset_spec_versions |
| shot_design_shots | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,artifact_id,design_unit_id → shot_design_units; project_id,scene_id → scenes; project_id,shot_id → shots |
| shot_line_coverage | project_id, id | project_id → projects; project_id,coverage_version_id → artifact_versions; project_id,line_id → script_lines; project_id,shot_id → shots |
| sound_cues | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,execution_id → execution_instances; project_id,line_id → script_lines; project_id,lipsync_version_id → artifact_versions; project_id,scope_object_id → creative_objects; project_id,subtitle_version_id → artifact_versions; project_id,voice_spec_id → voice_spec_versions |
| spatial_cameras | project_id, version_id, camera_key | project_id → projects; project_id,version_id → spatial_scene_versions |
| spatial_objects | project_id, version_id, object_key | project_id → projects; project_id,media_id → media_items; project_id,version_id → spatial_scene_versions |
| spatial_plan_tasks | project_id, id | project_id → projects; project_id,dispatch_id → role_dispatches; project_id,output_version_id → spatial_scene_versions; project_id,plan_artifact_id → artifact_versions; project_id,version_id → spatial_scene_versions |
| state_versions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,artifact_id,source_sha256 → artifact_versions; project_id,location_id → asset_identities; project_id,scene_id → scenes; project_id,shot_id → shots |
| timeline_items | project_id, id | project_id → projects; project_id,shot_id → shots; project_id,timeline_id → timeline_versions |
| asset_use_instances | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,asset_id → asset_identities; project_id,asset_id,spec_version_id → asset_spec_versions; project_id,scene_id → scenes; project_id,shot_id → shots; project_id,spec_version_id → asset_spec_versions; project_id,state_id → state_versions |
| binding_slots | project_id, id | project_id → projects; project_id,identity_asset_id → asset_identities; project_id,line_coverage_id → shot_line_coverage; project_id,target_object_id → creative_objects; project_id,variant_spec_id → asset_spec_versions |
| commerce_reservations | project_id, id | project_id → projects; project_id,job_id → generation_jobs; project_id,price_version_id → commerce_plan_versions |
| continuity_edges | project_id, id | project_id → projects; project_id,entry_state_id → state_versions; project_id,evidence_version_id → artifact_versions; project_id,exit_state_id → state_versions; project_id,from_shot_id → shots; project_id,to_shot_id → shots |
| creative_canvas_nodes | project_id, version_id, node_key | project_id → projects; project_id,job_id → generation_jobs; project_id,media_id → media_items; project_id,version_id → creative_canvas_versions |
| cue_shots | project_id, id | project_id → projects; project_id,cue_id → sound_cues; project_id,shot_id → shots |
| cue_timeline_items | project_id, id | project_id → projects; project_id,cue_id → sound_cues; project_id,item_id → timeline_items |
| intelligent_dependencies | project_id, version_id, unit_key, source_version_id, source_unit_key | project_id → projects; project_id,source_version_id,source_unit_key → intelligent_units; project_id,version_id,unit_key → intelligent_units |
| intelligent_runs | project_id, id | project_id → projects; project_id,draft_artifact_id → artifact_versions; project_id,run_artifact_id → artifact_versions; project_id,version_id,unit_key → intelligent_units |
| job_budget_reservations | project_id, id | project_id → projects; project_id,job_id → generation_jobs; project_id,limit_revision,unit → budget_limit_versions |
| job_events | project_id, id | project_id → projects; project_id,job_id → generation_jobs |
| job_input_versions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,artifact_id,sha256 → artifact_versions; project_id,job_id → generation_jobs |
| job_outputs | project_id, id | project_id → projects; project_id,job_id → generation_jobs; project_id,media_id → media_items |
| quality_observations | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,criteria_artifact_id → artifact_versions; project_id,job_id → generation_jobs; project_id,media_id → media_items; project_id,method_artifact_id → artifact_versions |
| service_api_call_jobs | project_id, id | project_id → projects; project_id,call_event_id → service_api_calls; project_id,job_id → generation_jobs |
| spatial_exports | project_id, id | project_id → projects; project_id,version_id,camera_key → spatial_cameras |
| spatial_plan_decisions | project_id, id | project_id → projects; project_id,task_id → spatial_plan_tasks |
| state_entity_refs | project_id, id | project_id → projects; project_id,asset_id → asset_identities; project_id,asset_id,spec_version_id → asset_spec_versions; project_id,spec_version_id → asset_spec_versions; project_id,state_id → state_versions |
| artifact_review_notes | project_id, id | project_id → projects; project_id,artifact_id,artifact_sha256 → artifact_versions; project_id,design_unit_id → shot_design_units; project_id,instance_id → asset_use_instances; project_id,render_id → render_versions; project_id,render_output_id → render_outputs; project_id,spec_version_id → asset_spec_versions |
| asset_requirements | project_id, id | category_code → asset_categories; project_id → projects; project_id,artifact_id → artifact_versions; project_id,artifact_id,source_sha256 → artifact_versions; project_id,asset_id → asset_identities; project_id,asset_id,spec_version_id → asset_spec_versions; project_id,instance_id → asset_use_instances; project_id,scene_id → scenes; project_id,shot_id → shots; project_id,spec_version_id → asset_spec_versions |
| binding_candidates | project_id, id | project_id → projects; project_id,media_id → media_items; project_id,slot_id → binding_slots; project_id,spec_version_id → artifact_versions |
| canvas_agent_turns | project_id, id | project_id → projects; project_id,dispatch_id → role_dispatches; project_id,output_version_id → creative_canvas_versions; project_id,parent_turn_id → canvas_agent_turns; project_id,plan_artifact_id → artifact_versions; project_id,run_artifact_id → artifact_versions; project_id,session_id → canvas_agent_sessions; project_id,target_shot_id → shots; project_id,version_id → creative_canvas_versions; project_id,version_id,target_node_key → creative_canvas_nodes |
| canvas_execution_steps | project_id, id | project_id → projects; project_id,asset_id → asset_identities; project_id,run_artifact_id → artifact_versions; project_id,shot_id → shots; project_id,source_step_id → canvas_execution_steps; project_id,spec_id → asset_spec_versions; project_id,version_id,node_key → creative_canvas_nodes |
| commerce_ledger | project_id, id | project_id → projects; project_id,bucket_id → commerce_buckets; project_id,reservation_id → commerce_reservations |
| creative_canvas_edges | project_id, version_id, edge_key | project_id → projects; project_id,version_id,source_key,source_type → creative_canvas_nodes; project_id,version_id,target_key,target_type → creative_canvas_nodes |
| creative_canvas_preparations | project_id, id | project_id → projects; project_id,job_id → generation_jobs; project_id,version_id,node_key → creative_canvas_nodes |
| creative_canvas_runs | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,version_id,node_key → creative_canvas_nodes |
| cue_slots | project_id, id | project_id → projects; project_id,cue_id → sound_cues; project_id,slot_id → binding_slots |
| execution_participants | project_id, id | project_id → projects; project_id,execution_id → execution_instances; project_id,instance_id → asset_use_instances |
| execution_slots | project_id, id | project_id → projects; project_id,execution_id → execution_instances; project_id,slot_id → binding_slots |
| instance_interactions | project_id, id | project_id → projects; project_id,artifact_id → artifact_versions; project_id,object_id → asset_use_instances; project_id,subject_id → asset_use_instances |
| spatial_export_outputs | project_id, id | project_id → projects; project_id,export_id → spatial_exports; project_id,media_id → media_items |
| binding_decisions | project_id, id | project_id → projects; project_id,slot_id → binding_slots; project_id,slot_id,candidate_id → binding_candidates |
| canvas_agent_action_results | project_id, turn_id, ordinal | project_id → projects; project_id,base_version_id → creative_canvas_versions; project_id,output_version_id → creative_canvas_versions; project_id,run_artifact_id → artifact_versions; project_id,turn_id → canvas_agent_turns |
| canvas_agent_decisions | project_id, id | project_id → projects; project_id,turn_id → canvas_agent_turns |
| canvas_agent_models | project_id, turn_id, ordinal | model_id → provider_models; project_id → projects; project_id,turn_id → canvas_agent_turns |
| canvas_agent_refs | project_id, turn_id, node_key | project_id → projects; project_id,turn_id,version_id → canvas_agent_turns; project_id,version_id,node_key → creative_canvas_nodes |
| canvas_execution_models | project_id, step_id, ordinal | model_id → provider_models; project_id → projects; project_id,step_id → canvas_execution_steps |
| edit_preview_jobs | project_id, id | project_id → projects; project_id,dispatch_id → role_dispatches; project_id,draft_artifact_id → artifact_versions; project_id,note_id → artifact_review_notes; project_id,render_id → render_versions; project_id,source_artifact_id → artifact_versions |
| library_cart_imports | project_id, id | cart_id → library_cart_items; cart_id,actor → library_cart_items; project_id → projects; project_id,candidate_id → binding_candidates; project_id,media_id → media_items; project_id,target_object_id → creative_objects |
| media_reviews | project_id, id | project_id → projects; project_id,candidate_id → binding_candidates; project_id,check_id → media_checks; project_id,project_revision → project_revisions |
| requirement_line_refs | project_id, requirement_id, line_id | project_id,line_id → script_lines; project_id,requirement_id → asset_requirements |
| requirement_slots | project_id, requirement_id, slot_id, role | project_id,requirement_id → asset_requirements; project_id,slot_id → binding_slots |
| access_review_submissions | id | project_id → projects; project_id,candidate_id → binding_candidates; project_id,candidate_id,review_id → media_reviews; project_id,supersedes_id → access_review_submissions; submitted_by → access_identities |
| binding_selection_delegations | project_id, decision_id | project_id,candidate_id,review_id → media_reviews; project_id,delegation_artifact_id,approval_decision_id → artifact_decisions; project_id,slot_id,candidate_id,decision_id → binding_decisions |
| binding_trial_adoptions | project_id, decision_id, run_version_id | project_id,animatic_version_id,animatic_approval_id → artifact_decisions; project_id,decision_id → binding_decisions; project_id,run_version_id → artifact_versions |
| current_bindings | project_id, slot_id | project_id,slot_id,candidate_id → binding_candidates; project_id,slot_id,candidate_id,decision_id → binding_decisions |
| dispatch_media_refs | project_id, dispatch_id, media_id, role | project_id,binding_decision_id → binding_decisions; project_id,dispatch_id → role_dispatches; project_id,media_id → media_items |
| edit_preview_attempts | project_id, id | project_id → projects; project_id,job_id → edit_preview_jobs |
| edit_preview_inputs | project_id, id | blob_id,blob_sha256 → media_blobs; project_id → projects; project_id,binding_decision_id → binding_decisions; project_id,job_id → edit_preview_jobs; project_id,media_id → media_items; project_id,media_id,blob_id → media_items; project_id,timeline_item_id → timeline_items |
| intelligent_media | project_id, version_id, unit_key, purpose, media_id | project_id → projects; project_id,decision_id → binding_decisions; project_id,media_id → media_items; project_id,spatial_export_id → spatial_exports; project_id,version_id,unit_key → intelligent_units |
| job_input_media | project_id, id | blob_id,blob_sha256 → media_blobs; project_id → projects; project_id,binding_decision_id → binding_decisions; project_id,job_id → generation_jobs; project_id,media_id → media_items; project_id,media_id,blob_id → media_items |
| render_inputs | project_id, id | blob_id,blob_sha256 → media_blobs; project_id → projects; project_id,binding_decision_id → binding_decisions; project_id,media_id → media_items; project_id,media_id,blob_id → media_items; project_id,render_id → render_versions |
| review_responses | project_id, id | project_id → projects; project_id,artifact_note_id → artifact_review_notes; project_id,media_review_id → media_reviews; project_id,script_note_id → script_notes |
| timeline_item_media | project_id, id | blob_id,blob_sha256 → media_blobs; project_id → projects; project_id,binding_decision_id → binding_decisions; project_id,item_id → timeline_items; project_id,media_id → media_items; project_id,media_id,blob_id → media_items |
| edit_preview_outputs | project_id, id | blob_id,blob_sha256 → media_blobs; project_id → projects; project_id,attempt_id → edit_preview_attempts; project_id,job_id → edit_preview_jobs |
| review_dispatches | project_id, response_id, dispatch_id | project_id,dispatch_id → role_dispatches; project_id,response_id → review_responses |
| review_proposals | project_id, response_id, artifact_id | project_id,artifact_id → artifact_versions; project_id,response_id → review_responses |
| review_script_runs | project_id, response_id, run_id | project_id,response_id → review_responses; project_id,run_id → script_suggestion_runs |

```mermaid
erDiagram
    access_identities ||--o{ access_commands : "references"
    access_identities ||--o{ access_credentials : "references"
    access_identities ||--o{ access_invitations : "references"
    access_identities ||--o{ access_project_members : "references"
    access_identities ||--o{ access_projects : "references"
    access_identities ||--o{ access_review_submissions : "references"
    access_identities ||--o{ access_shares : "references"
    access_identities ||--o{ access_workspace_members : "references"
    access_identities ||--o{ access_workspaces : "references"
    access_identities ||--o{ service_announcements : "references"
    access_identities ||--o{ service_api_keys : "references"
    access_identities ||--o{ service_configuration_versions : "references"
    access_identities ||--o{ service_export_files : "references"
    access_identities ||--o{ service_request_events : "references"
    access_identities ||--o{ service_requests : "references"
    access_projects ||--o{ access_invitations : "references"
    access_projects ||--o{ access_project_members : "references"
    access_review_submissions ||--o{ access_review_submissions : "references"
    access_shares ||--o{ access_share_media : "references"
    access_workspaces ||--o{ access_invitations : "references"
    access_workspaces ||--o{ access_projects : "references"
    access_workspaces ||--o{ access_workspace_members : "references"
    access_workspaces ||--o{ access_workspaces : "references"
    access_workspaces ||--o{ library_catalog_edits : "references"
    artifact_decisions ||--o{ binding_selection_delegations : "references"
    artifact_decisions ||--o{ binding_trial_adoptions : "references"
    artifact_decisions ||--o{ current_artifact_versions : "references"
    artifact_review_notes ||--o{ edit_preview_jobs : "references"
    artifact_review_notes ||--o{ review_responses : "references"
    artifact_versions ||--o{ artifact_asset_spec_refs : "references"
    artifact_versions ||--o{ artifact_category_links : "references"
    artifact_versions ||--o{ artifact_decisions : "references"
    artifact_versions ||--o{ artifact_dependencies : "references"
    artifact_versions ||--o{ artifact_object_scopes : "references"
    artifact_versions ||--o{ artifact_review_notes : "references"
    artifact_versions ||--o{ artifact_versions : "references"
    artifact_versions ||--o{ asset_requirements : "references"
    artifact_versions ||--o{ asset_spec_versions : "references"
    artifact_versions ||--o{ asset_use_instances : "references"
    artifact_versions ||--o{ binding_candidates : "references"
    artifact_versions ||--o{ binding_trial_adoptions : "references"
    artifact_versions ||--o{ canvas_agent_action_results : "references"
    artifact_versions ||--o{ canvas_agent_turns : "references"
    artifact_versions ||--o{ canvas_execution_steps : "references"
    artifact_versions ||--o{ character_voice_bindings : "references"
    artifact_versions ||--o{ continuity_edges : "references"
    artifact_versions ||--o{ creative_canvas_runs : "references"
    artifact_versions ||--o{ creative_tool_imports : "references"
    artifact_versions ||--o{ current_artifact_versions : "references"
    artifact_versions ||--o{ dispatch_inputs : "references"
    artifact_versions ||--o{ dispatch_result_artifacts : "references"
    artifact_versions ||--o{ edit_preview_jobs : "references"
    artifact_versions ||--o{ edit_timeline_handoffs : "references"
    artifact_versions ||--o{ execution_instances : "references"
    artifact_versions ||--o{ generation_jobs : "references"
    artifact_versions ||--o{ instance_interactions : "references"
    artifact_versions ||--o{ intelligent_asset_runs : "references"
    artifact_versions ||--o{ intelligent_definitions : "references"
    artifact_versions ||--o{ intelligent_runs : "references"
    artifact_versions ||--o{ intelligent_tasks : "references"
    artifact_versions ||--o{ intelligent_versions : "references"
    artifact_versions ||--o{ job_input_versions : "references"
    artifact_versions ||--o{ method_evaluations : "references"
    artifact_versions ||--o{ quality_observations : "references"
    artifact_versions ||--o{ render_versions : "references"
    artifact_versions ||--o{ review_proposals : "references"
    artifact_versions ||--o{ role_memory_artifacts : "references"
    artifact_versions ||--o{ scene_location_refs : "references"
    artifact_versions ||--o{ script_drafts : "references"
    artifact_versions ||--o{ script_line_dispositions : "references"
    artifact_versions ||--o{ script_lines : "references"
    artifact_versions ||--o{ script_notes : "references"
    artifact_versions ||--o{ service_api_calls : "references"
    artifact_versions ||--o{ service_requests : "references"
    artifact_versions ||--o{ shot_design_shots : "references"
    artifact_versions ||--o{ shot_design_units : "references"
    artifact_versions ||--o{ shot_line_coverage : "references"
    artifact_versions ||--o{ sound_cues : "references"
    artifact_versions ||--o{ spatial_plan_tasks : "references"
    artifact_versions ||--o{ state_versions : "references"
    artifact_versions ||--o{ text_tool_attempts : "references"
    artifact_versions ||--o{ text_tool_copies : "references"
    artifact_versions ||--o{ text_tool_units : "references"
    artifact_versions ||--o{ timeline_versions : "references"
    artifact_versions ||--o{ voice_spec_versions : "references"
    asset_categories ||--o{ artifact_category_links : "references"
    asset_categories ||--o{ asset_categories : "references"
    asset_categories ||--o{ asset_requirements : "references"
    asset_categories ||--o{ identity_category_links : "references"
    asset_categories ||--o{ media_category_links : "references"
    asset_identities ||--o{ asset_requirements : "references"
    asset_identities ||--o{ asset_spec_versions : "references"
    asset_identities ||--o{ asset_use_instances : "references"
    asset_identities ||--o{ binding_slots : "references"
    asset_identities ||--o{ canvas_execution_steps : "references"
    asset_identities ||--o{ character_voice_bindings : "references"
    asset_identities ||--o{ generation_jobs : "references"
    asset_identities ||--o{ identity_category_links : "references"
    asset_identities ||--o{ intelligent_assets : "references"
    asset_identities ||--o{ media_import_items : "references"
    asset_identities ||--o{ scene_location_refs : "references"
    asset_identities ||--o{ script_lines : "references"
    asset_identities ||--o{ state_entity_refs : "references"
    asset_identities ||--o{ state_versions : "references"
    asset_identities ||--o{ voice_spec_versions : "references"
    asset_requirements ||--o{ requirement_line_refs : "references"
    asset_requirements ||--o{ requirement_slots : "references"
    asset_spec_versions ||--o{ artifact_asset_spec_refs : "references"
    asset_spec_versions ||--o{ artifact_review_notes : "references"
    asset_spec_versions ||--o{ asset_requirements : "references"
    asset_spec_versions ||--o{ asset_use_instances : "references"
    asset_spec_versions ||--o{ binding_slots : "references"
    asset_spec_versions ||--o{ canvas_execution_steps : "references"
    asset_spec_versions ||--o{ intelligent_assets : "references"
    asset_spec_versions ||--o{ scene_location_refs : "references"
    asset_spec_versions ||--o{ state_entity_refs : "references"
    asset_use_instances ||--o{ artifact_review_notes : "references"
    asset_use_instances ||--o{ asset_requirements : "references"
    asset_use_instances ||--o{ execution_participants : "references"
    asset_use_instances ||--o{ instance_interactions : "references"
    binding_candidates ||--o{ access_review_submissions : "references"
    binding_candidates ||--o{ binding_decisions : "references"
    binding_candidates ||--o{ current_bindings : "references"
    binding_candidates ||--o{ library_cart_imports : "references"
    binding_candidates ||--o{ media_reviews : "references"
    binding_decisions ||--o{ binding_selection_delegations : "references"
    binding_decisions ||--o{ binding_trial_adoptions : "references"
    binding_decisions ||--o{ current_bindings : "references"
    binding_decisions ||--o{ dispatch_media_refs : "references"
    binding_decisions ||--o{ edit_preview_inputs : "references"
    binding_decisions ||--o{ intelligent_media : "references"
    binding_decisions ||--o{ job_input_media : "references"
    binding_decisions ||--o{ render_inputs : "references"
    binding_decisions ||--o{ timeline_item_media : "references"
    binding_slots ||--o{ binding_candidates : "references"
    binding_slots ||--o{ binding_decisions : "references"
    binding_slots ||--o{ cue_slots : "references"
    binding_slots ||--o{ execution_slots : "references"
    binding_slots ||--o{ requirement_slots : "references"
    budget_limit_versions ||--o{ job_budget_reservations : "references"
    canvas_agent_sessions ||--o{ canvas_agent_turns : "references"
    canvas_agent_turns ||--o{ canvas_agent_action_results : "references"
    canvas_agent_turns ||--o{ canvas_agent_decisions : "references"
    canvas_agent_turns ||--o{ canvas_agent_models : "references"
    canvas_agent_turns ||--o{ canvas_agent_refs : "references"
    canvas_agent_turns ||--o{ canvas_agent_turns : "references"
    canvas_execution_steps ||--o{ canvas_execution_models : "references"
    canvas_execution_steps ||--o{ canvas_execution_steps : "references"
    canvas_templates ||--o{ canvas_template_copies : "references"
    canvas_templates ||--o{ canvas_template_favorites : "references"
    commerce_buckets ||--o{ commerce_buckets : "references"
    commerce_buckets ||--o{ commerce_ledger : "references"
    commerce_buckets ||--o{ commerce_redemptions : "references"
    commerce_campaigns ||--o{ commerce_redemptions : "references"
    commerce_orders ||--o{ commerce_buckets : "references"
    commerce_orders ||--o{ commerce_invoices : "references"
    commerce_orders ||--o{ commerce_orders : "references"
    commerce_orders ||--o{ commerce_payment_events : "references"
    commerce_plan_versions ||--o{ commerce_orders : "references"
    commerce_plan_versions ||--o{ commerce_rates : "references"
    commerce_plan_versions ||--o{ commerce_reservations : "references"
    commerce_plan_versions ||--o{ commerce_settings : "references"
    commerce_reservations ||--o{ commerce_ledger : "references"
    creative_canvas_nodes ||--o{ canvas_agent_refs : "references"
    creative_canvas_nodes ||--o{ canvas_agent_turns : "references"
    creative_canvas_nodes ||--o{ canvas_execution_steps : "references"
    creative_canvas_nodes ||--o{ creative_canvas_edges : "references"
    creative_canvas_nodes ||--o{ creative_canvas_preparations : "references"
    creative_canvas_nodes ||--o{ creative_canvas_runs : "references"
    creative_canvas_versions ||--o{ access_shares : "references"
    creative_canvas_versions ||--o{ canvas_agent_action_results : "references"
    creative_canvas_versions ||--o{ canvas_agent_turns : "references"
    creative_canvas_versions ||--o{ canvas_templates : "references"
    creative_canvas_versions ||--o{ creative_canvas_nodes : "references"
    creative_canvas_versions ||--o{ creative_canvas_versions : "references"
    creative_canvas_versions ||--o{ creative_canvases : "references"
    creative_canvases ||--o{ access_shares : "references"
    creative_canvases ||--o{ canvas_agent_sessions : "references"
    creative_canvases ||--o{ canvas_template_copies : "references"
    creative_canvases ||--o{ creative_canvas_versions : "references"
    creative_objects ||--o{ artifact_object_scopes : "references"
    creative_objects ||--o{ asset_identities : "references"
    creative_objects ||--o{ binding_slots : "references"
    creative_objects ||--o{ episodes : "references"
    creative_objects ||--o{ library_cart_imports : "references"
    creative_objects ||--o{ management_object_states : "references"
    creative_objects ||--o{ object_folder_memberships : "references"
    creative_objects ||--o{ role_dispatches : "references"
    creative_objects ||--o{ role_memories : "references"
    creative_objects ||--o{ role_memory_targets : "references"
    creative_objects ||--o{ scenes : "references"
    creative_objects ||--o{ sequences : "references"
    creative_objects ||--o{ shots : "references"
    creative_objects ||--o{ sound_cues : "references"
    creative_objects ||--o{ works : "references"
    dispatch_returns ||--o{ dispatch_result_artifacts : "references"
    edit_preview_attempts ||--o{ edit_preview_outputs : "references"
    edit_preview_jobs ||--o{ edit_preview_attempts : "references"
    edit_preview_jobs ||--o{ edit_preview_inputs : "references"
    edit_preview_jobs ||--o{ edit_preview_outputs : "references"
    edit_revisions ||--o{ edit_render_jobs : "references"
    edit_revisions ||--o{ edit_revision_media : "references"
    edit_revisions ||--o{ edit_timeline_handoffs : "references"
    edit_revisions ||--o{ edit_workspaces : "references"
    edit_workspaces ||--o{ edit_revisions : "references"
    episodes ||--o{ creative_canvases : "references"
    episodes ||--o{ creative_tool_imports : "references"
    episodes ||--o{ edit_workspaces : "references"
    episodes ||--o{ intelligent_workflows : "references"
    episodes ||--o{ media_import_batches : "references"
    episodes ||--o{ scenes : "references"
    episodes ||--o{ spatial_scenes : "references"
    episodes ||--o{ text_tool_units : "references"
    episodes ||--o{ timeline_versions : "references"
    execution_instances ||--o{ execution_materials : "references"
    execution_instances ||--o{ execution_participants : "references"
    execution_instances ||--o{ execution_shots : "references"
    execution_instances ||--o{ execution_slots : "references"
    execution_instances ||--o{ sound_cues : "references"
    generation_jobs ||--o{ commerce_reservations : "references"
    generation_jobs ||--o{ creative_canvas_nodes : "references"
    generation_jobs ||--o{ creative_canvas_preparations : "references"
    generation_jobs ||--o{ job_budget_reservations : "references"
    generation_jobs ||--o{ job_events : "references"
    generation_jobs ||--o{ job_input_media : "references"
    generation_jobs ||--o{ job_input_versions : "references"
    generation_jobs ||--o{ job_outputs : "references"
    generation_jobs ||--o{ quality_observations : "references"
    generation_jobs ||--o{ service_api_call_jobs : "references"
    intelligent_assets ||--o{ intelligent_asset_runs : "references"
    intelligent_definitions ||--o{ intelligent_workflows : "references"
    intelligent_tasks ||--o{ intelligent_decisions : "references"
    intelligent_units ||--o{ intelligent_dependencies : "references"
    intelligent_units ||--o{ intelligent_media : "references"
    intelligent_units ||--o{ intelligent_runs : "references"
    intelligent_versions ||--o{ intelligent_assets : "references"
    intelligent_versions ||--o{ intelligent_tasks : "references"
    intelligent_versions ||--o{ intelligent_units : "references"
    intelligent_versions ||--o{ intelligent_versions : "references"
    intelligent_workflows ||--o{ intelligent_versions : "references"
    library_cart_items ||--o{ library_cart_imports : "references"
    library_catalog_edits ||--o{ library_catalog_tags : "references"
    library_entries ||--o{ library_entry_decisions : "references"
    library_entries ||--o{ library_entry_versions : "references"
    library_entry_versions ||--o{ library_catalog_edits : "references"
    library_entry_versions ||--o{ library_entries : "references"
    library_entry_versions ||--o{ library_version_media : "references"
    library_version_media ||--o{ library_cart_items : "references"
    library_version_media ||--o{ library_download_requests : "references"
    library_version_media ||--o{ library_reuses : "references"
    management_folders ||--o{ management_folders : "references"
    management_folders ||--o{ media_folder_memberships : "references"
    management_folders ||--o{ object_folder_memberships : "references"
    media_blobs ||--o{ blob_locations : "references"
    media_blobs ||--o{ creative_tool_imports : "references"
    media_blobs ||--o{ edit_preview_inputs : "references"
    media_blobs ||--o{ edit_preview_outputs : "references"
    media_blobs ||--o{ edit_render_jobs : "references"
    media_blobs ||--o{ edit_revision_media : "references"
    media_blobs ||--o{ job_input_media : "references"
    media_blobs ||--o{ library_version_media : "references"
    media_blobs ||--o{ media_checks : "references"
    media_blobs ||--o{ media_items : "references"
    media_blobs ||--o{ media_renditions : "references"
    media_blobs ||--o{ render_caption_inputs : "references"
    media_blobs ||--o{ render_inputs : "references"
    media_blobs ||--o{ timeline_item_media : "references"
    media_checks ||--o{ media_reviews : "references"
    media_import_batches ||--o{ media_import_items : "references"
    media_items ||--o{ access_share_media : "references"
    media_items ||--o{ binding_candidates : "references"
    media_items ||--o{ creative_canvas_nodes : "references"
    media_items ||--o{ creative_tool_imports : "references"
    media_items ||--o{ dispatch_media_refs : "references"
    media_items ||--o{ edit_preview_inputs : "references"
    media_items ||--o{ edit_revision_media : "references"
    media_items ||--o{ execution_materials : "references"
    media_items ||--o{ intelligent_media : "references"
    media_items ||--o{ job_input_media : "references"
    media_items ||--o{ job_outputs : "references"
    media_items ||--o{ library_cart_imports : "references"
    media_items ||--o{ library_reuses : "references"
    media_items ||--o{ media_category_links : "references"
    media_items ||--o{ media_checks : "references"
    media_items ||--o{ media_folder_memberships : "references"
    media_items ||--o{ media_import_items : "references"
    media_items ||--o{ media_lifecycle_decisions : "references"
    media_items ||--o{ media_recycle_actions : "references"
    media_items ||--o{ media_renditions : "references"
    media_items ||--o{ media_sources : "references"
    media_items ||--o{ method_evaluations : "references"
    media_items ||--o{ operation_inputs : "references"
    media_items ||--o{ operation_outputs : "references"
    media_items ||--o{ preview_jobs : "references"
    media_items ||--o{ quality_observations : "references"
    media_items ||--o{ render_caption_inputs : "references"
    media_items ||--o{ render_inputs : "references"
    media_items ||--o{ render_outputs : "references"
    media_items ||--o{ rights_decisions : "references"
    media_items ||--o{ service_requests : "references"
    media_items ||--o{ shot_design_panels : "references"
    media_items ||--o{ spatial_export_outputs : "references"
    media_items ||--o{ spatial_objects : "references"
    media_items ||--o{ timeline_item_media : "references"
    media_items ||--o{ voice_spec_versions : "references"
    media_lifecycle_decisions ||--o{ media_recycle_actions : "references"
    media_operations ||--o{ operation_inputs : "references"
    media_operations ||--o{ operation_outputs : "references"
    media_reviews ||--o{ access_review_submissions : "references"
    media_reviews ||--o{ binding_selection_delegations : "references"
    media_reviews ||--o{ review_responses : "references"
    operation_inputs ||--o{ operation_inputs : "references"
    parse_attempts ||--o{ source_extractions : "references"
    parse_jobs ||--o{ parse_attempts : "references"
    parse_jobs ||--o{ parse_job_inputs : "references"
    project_revisions ||--o{ media_checks : "references"
    project_revisions ||--o{ media_reviews : "references"
    projects ||--o{ access_projects : "references"
    projects ||--o{ access_review_submissions : "references"
    projects ||--o{ access_shares : "references"
    projects ||--o{ artifact_decisions : "references"
    projects ||--o{ artifact_review_notes : "references"
    projects ||--o{ artifact_versions : "references"
    projects ||--o{ asset_identities : "references"
    projects ||--o{ asset_requirements : "references"
    projects ||--o{ asset_spec_versions : "references"
    projects ||--o{ asset_use_instances : "references"
    projects ||--o{ binding_candidates : "references"
    projects ||--o{ binding_decisions : "references"
    projects ||--o{ binding_slots : "references"
    projects ||--o{ budget_limit_versions : "references"
    projects ||--o{ canvas_agent_action_results : "references"
    projects ||--o{ canvas_agent_decisions : "references"
    projects ||--o{ canvas_agent_models : "references"
    projects ||--o{ canvas_agent_refs : "references"
    projects ||--o{ canvas_agent_sessions : "references"
    projects ||--o{ canvas_agent_turns : "references"
    projects ||--o{ canvas_execution_models : "references"
    projects ||--o{ canvas_execution_steps : "references"
    projects ||--o{ canvas_template_copies : "references"
    projects ||--o{ canvas_template_favorites : "references"
    projects ||--o{ canvas_templates : "references"
    projects ||--o{ character_voice_bindings : "references"
    projects ||--o{ command_receipts : "references"
    projects ||--o{ commerce_buckets : "references"
    projects ||--o{ commerce_campaigns : "references"
    projects ||--o{ commerce_invoices : "references"
    projects ||--o{ commerce_ledger : "references"
    projects ||--o{ commerce_orders : "references"
    projects ||--o{ commerce_payment_events : "references"
    projects ||--o{ commerce_plan_versions : "references"
    projects ||--o{ commerce_rates : "references"
    projects ||--o{ commerce_redemptions : "references"
    projects ||--o{ commerce_reservations : "references"
    projects ||--o{ commerce_settings : "references"
    projects ||--o{ continuity_edges : "references"
    projects ||--o{ creative_canvas_edges : "references"
    projects ||--o{ creative_canvas_nodes : "references"
    projects ||--o{ creative_canvas_preparations : "references"
    projects ||--o{ creative_canvas_runs : "references"
    projects ||--o{ creative_canvas_versions : "references"
    projects ||--o{ creative_canvases : "references"
    projects ||--o{ creative_objects : "references"
    projects ||--o{ creative_tool_imports : "references"
    projects ||--o{ cue_shots : "references"
    projects ||--o{ cue_slots : "references"
    projects ||--o{ cue_timeline_items : "references"
    projects ||--o{ dispatch_consumptions : "references"
    projects ||--o{ dispatch_returns : "references"
    projects ||--o{ draft_source_refs : "references"
    projects ||--o{ edit_preview_attempts : "references"
    projects ||--o{ edit_preview_inputs : "references"
    projects ||--o{ edit_preview_jobs : "references"
    projects ||--o{ edit_preview_outputs : "references"
    projects ||--o{ edit_render_jobs : "references"
    projects ||--o{ edit_revision_media : "references"
    projects ||--o{ edit_revisions : "references"
    projects ||--o{ edit_timeline_handoffs : "references"
    projects ||--o{ edit_workspaces : "references"
    projects ||--o{ episodes : "references"
    projects ||--o{ execution_instances : "references"
    projects ||--o{ execution_materials : "references"
    projects ||--o{ execution_participants : "references"
    projects ||--o{ execution_shots : "references"
    projects ||--o{ execution_slots : "references"
    projects ||--o{ generation_jobs : "references"
    projects ||--o{ instance_interactions : "references"
    projects ||--o{ intelligent_asset_runs : "references"
    projects ||--o{ intelligent_assets : "references"
    projects ||--o{ intelligent_decisions : "references"
    projects ||--o{ intelligent_definitions : "references"
    projects ||--o{ intelligent_dependencies : "references"
    projects ||--o{ intelligent_media : "references"
    projects ||--o{ intelligent_runs : "references"
    projects ||--o{ intelligent_tasks : "references"
    projects ||--o{ intelligent_units : "references"
    projects ||--o{ intelligent_versions : "references"
    projects ||--o{ intelligent_workflows : "references"
    projects ||--o{ job_budget_reservations : "references"
    projects ||--o{ job_events : "references"
    projects ||--o{ job_input_media : "references"
    projects ||--o{ job_input_versions : "references"
    projects ||--o{ job_outputs : "references"
    projects ||--o{ library_cart_imports : "references"
    projects ||--o{ library_reuses : "references"
    projects ||--o{ management_folders : "references"
    projects ||--o{ management_object_states : "references"
    projects ||--o{ management_project_states : "references"
    projects ||--o{ management_retention : "references"
    projects ||--o{ media_checks : "references"
    projects ||--o{ media_folder_memberships : "references"
    projects ||--o{ media_import_batches : "references"
    projects ||--o{ media_import_items : "references"
    projects ||--o{ media_items : "references"
    projects ||--o{ media_lifecycle_decisions : "references"
    projects ||--o{ media_operations : "references"
    projects ||--o{ media_recycle_actions : "references"
    projects ||--o{ media_renditions : "references"
    projects ||--o{ media_reviews : "references"
    projects ||--o{ media_sources : "references"
    projects ||--o{ method_evaluations : "references"
    projects ||--o{ object_folder_memberships : "references"
    projects ||--o{ operation_inputs : "references"
    projects ||--o{ operation_outputs : "references"
    projects ||--o{ parse_attempts : "references"
    projects ||--o{ parse_job_inputs : "references"
    projects ||--o{ parse_jobs : "references"
    projects ||--o{ preview_jobs : "references"
    projects ||--o{ project_revisions : "references"
    projects ||--o{ quality_observations : "references"
    projects ||--o{ render_caption_inputs : "references"
    projects ||--o{ render_inputs : "references"
    projects ||--o{ render_outputs : "references"
    projects ||--o{ render_versions : "references"
    projects ||--o{ review_responses : "references"
    projects ||--o{ rights_decisions : "references"
    projects ||--o{ role_dispatches : "references"
    projects ||--o{ role_memories : "references"
    projects ||--o{ role_memory_decisions : "references"
    projects ||--o{ role_memory_versions : "references"
    projects ||--o{ scene_location_refs : "references"
    projects ||--o{ scenes : "references"
    projects ||--o{ script_drafts : "references"
    projects ||--o{ script_line_dispositions : "references"
    projects ||--o{ script_line_sources : "references"
    projects ||--o{ script_lines : "references"
    projects ||--o{ script_note_decisions : "references"
    projects ||--o{ script_notes : "references"
    projects ||--o{ script_suggestion_decisions : "references"
    projects ||--o{ script_suggestion_runs : "references"
    projects ||--o{ script_suggestions : "references"
    projects ||--o{ sequences : "references"
    projects ||--o{ service_announcements : "references"
    projects ||--o{ service_api_call_jobs : "references"
    projects ||--o{ service_api_calls : "references"
    projects ||--o{ service_api_keys : "references"
    projects ||--o{ service_configuration_versions : "references"
    projects ||--o{ service_export_files : "references"
    projects ||--o{ service_request_events : "references"
    projects ||--o{ service_requests : "references"
    projects ||--o{ shot_design_panels : "references"
    projects ||--o{ shot_design_shots : "references"
    projects ||--o{ shot_design_units : "references"
    projects ||--o{ shot_line_coverage : "references"
    projects ||--o{ shots : "references"
    projects ||--o{ sound_cues : "references"
    projects ||--o{ source_anchors : "references"
    projects ||--o{ source_extractions : "references"
    projects ||--o{ source_versions : "references"
    projects ||--o{ spatial_cameras : "references"
    projects ||--o{ spatial_export_outputs : "references"
    projects ||--o{ spatial_exports : "references"
    projects ||--o{ spatial_objects : "references"
    projects ||--o{ spatial_plan_decisions : "references"
    projects ||--o{ spatial_plan_tasks : "references"
    projects ||--o{ spatial_scene_versions : "references"
    projects ||--o{ spatial_scenes : "references"
    projects ||--o{ state_entity_refs : "references"
    projects ||--o{ state_versions : "references"
    projects ||--o{ text_tool_attempts : "references"
    projects ||--o{ text_tool_copies : "references"
    projects ||--o{ text_tool_receipts : "references"
    projects ||--o{ text_tool_units : "references"
    projects ||--o{ timeline_item_media : "references"
    projects ||--o{ timeline_items : "references"
    projects ||--o{ timeline_versions : "references"
    projects ||--o{ voice_spec_versions : "references"
    projects ||--o{ works : "references"
    provider_models ||--o{ canvas_agent_models : "references"
    provider_models ||--o{ canvas_execution_models : "references"
    provider_models ||--o{ commerce_rates : "references"
    provider_models ||--o{ generation_jobs : "references"
    provider_models ||--o{ provider_configurations : "references"
    provider_models ||--o{ provider_routes : "references"
    providers ||--o{ generation_jobs : "references"
    providers ||--o{ provider_configurations : "references"
    providers ||--o{ provider_models : "references"
    providers ||--o{ provider_routes : "references"
    render_outputs ||--o{ artifact_review_notes : "references"
    render_versions ||--o{ artifact_review_notes : "references"
    render_versions ||--o{ edit_preview_jobs : "references"
    render_versions ||--o{ render_caption_inputs : "references"
    render_versions ||--o{ render_inputs : "references"
    render_versions ||--o{ render_outputs : "references"
    review_responses ||--o{ review_dispatches : "references"
    review_responses ||--o{ review_proposals : "references"
    review_responses ||--o{ review_script_runs : "references"
    rights_decisions ||--o{ library_reuses : "references"
    role_dispatches ||--o{ canvas_agent_turns : "references"
    role_dispatches ||--o{ dispatch_consumptions : "references"
    role_dispatches ||--o{ dispatch_inputs : "references"
    role_dispatches ||--o{ dispatch_media_refs : "references"
    role_dispatches ||--o{ dispatch_memory_refs : "references"
    role_dispatches ||--o{ dispatch_returns : "references"
    role_dispatches ||--o{ dispatch_sources : "references"
    role_dispatches ||--o{ edit_preview_jobs : "references"
    role_dispatches ||--o{ intelligent_tasks : "references"
    role_dispatches ||--o{ review_dispatches : "references"
    role_dispatches ||--o{ role_memories : "references"
    role_dispatches ||--o{ role_memory_versions : "references"
    role_dispatches ||--o{ spatial_plan_tasks : "references"
    role_memories ||--o{ role_memory_versions : "references"
    role_memory_decisions ||--o{ dispatch_memory_refs : "references"
    role_memory_versions ||--o{ dispatch_memory_refs : "references"
    role_memory_versions ||--o{ role_memory_artifacts : "references"
    role_memory_versions ||--o{ role_memory_decisions : "references"
    role_memory_versions ||--o{ role_memory_sources : "references"
    role_memory_versions ||--o{ role_memory_targets : "references"
    scenes ||--o{ asset_requirements : "references"
    scenes ||--o{ asset_use_instances : "references"
    scenes ||--o{ scene_location_refs : "references"
    scenes ||--o{ script_lines : "references"
    scenes ||--o{ sequences : "references"
    scenes ||--o{ shot_design_shots : "references"
    scenes ||--o{ shot_design_units : "references"
    scenes ||--o{ spatial_scenes : "references"
    scenes ||--o{ state_versions : "references"
    script_drafts ||--o{ draft_source_refs : "references"
    script_drafts ||--o{ script_suggestion_runs : "references"
    script_lines ||--o{ execution_instances : "references"
    script_lines ||--o{ requirement_line_refs : "references"
    script_lines ||--o{ script_line_dispositions : "references"
    script_lines ||--o{ script_line_sources : "references"
    script_lines ||--o{ shot_design_line_refs : "references"
    script_lines ||--o{ shot_line_coverage : "references"
    script_lines ||--o{ sound_cues : "references"
    script_notes ||--o{ review_responses : "references"
    script_notes ||--o{ script_note_anchors : "references"
    script_notes ||--o{ script_note_decisions : "references"
    script_suggestion_runs ||--o{ review_script_runs : "references"
    script_suggestion_runs ||--o{ script_run_suggestions : "references"
    script_suggestions ||--o{ script_run_suggestions : "references"
    script_suggestions ||--o{ script_suggestion_decisions : "references"
    sequences ||--o{ shots : "references"
    service_api_calls ||--o{ service_api_call_jobs : "references"
    service_api_keys ||--o{ service_api_calls : "references"
    service_requests ||--o{ service_export_files : "references"
    service_requests ||--o{ service_request_events : "references"
    shot_design_units ||--o{ artifact_review_notes : "references"
    shot_design_units ||--o{ shot_design_line_refs : "references"
    shot_design_units ||--o{ shot_design_panels : "references"
    shot_design_units ||--o{ shot_design_shots : "references"
    shot_line_coverage ||--o{ binding_slots : "references"
    shots ||--o{ asset_requirements : "references"
    shots ||--o{ asset_use_instances : "references"
    shots ||--o{ canvas_agent_turns : "references"
    shots ||--o{ canvas_execution_steps : "references"
    shots ||--o{ continuity_edges : "references"
    shots ||--o{ cue_shots : "references"
    shots ||--o{ edit_revision_media : "references"
    shots ||--o{ execution_shots : "references"
    shots ||--o{ generation_jobs : "references"
    shots ||--o{ intelligent_units : "references"
    shots ||--o{ scene_location_refs : "references"
    shots ||--o{ shot_design_shots : "references"
    shots ||--o{ shot_line_coverage : "references"
    shots ||--o{ state_versions : "references"
    shots ||--o{ timeline_items : "references"
    sound_cues ||--o{ cue_shots : "references"
    sound_cues ||--o{ cue_slots : "references"
    sound_cues ||--o{ cue_timeline_items : "references"
    source_anchors ||--o{ draft_source_refs : "references"
    source_anchors ||--o{ script_line_sources : "references"
    source_extractions ||--o{ source_anchors : "references"
    source_versions ||--o{ dispatch_sources : "references"
    source_versions ||--o{ library_reuses : "references"
    source_versions ||--o{ media_sources : "references"
    source_versions ||--o{ parse_job_inputs : "references"
    source_versions ||--o{ rights_decisions : "references"
    source_versions ||--o{ role_memory_sources : "references"
    source_versions ||--o{ source_anchors : "references"
    source_versions ||--o{ source_extractions : "references"
    source_versions ||--o{ source_intake_documents : "references"
    spatial_cameras ||--o{ spatial_exports : "references"
    spatial_exports ||--o{ intelligent_media : "references"
    spatial_exports ||--o{ spatial_export_outputs : "references"
    spatial_plan_tasks ||--o{ spatial_plan_decisions : "references"
    spatial_scene_versions ||--o{ intelligent_units : "references"
    spatial_scene_versions ||--o{ spatial_cameras : "references"
    spatial_scene_versions ||--o{ spatial_objects : "references"
    spatial_scene_versions ||--o{ spatial_plan_tasks : "references"
    spatial_scene_versions ||--o{ spatial_scenes : "references"
    spatial_scenes ||--o{ spatial_scene_versions : "references"
    state_versions ||--o{ asset_use_instances : "references"
    state_versions ||--o{ continuity_edges : "references"
    state_versions ||--o{ state_entity_refs : "references"
    text_tool_attempts ||--o{ text_tool_receipts : "references"
    text_tool_units ||--o{ text_tool_attempts : "references"
    text_tool_units ||--o{ text_tool_copies : "references"
    timeline_items ||--o{ cue_timeline_items : "references"
    timeline_items ||--o{ edit_preview_inputs : "references"
    timeline_items ||--o{ timeline_item_media : "references"
    timeline_versions ||--o{ render_versions : "references"
    timeline_versions ||--o{ timeline_items : "references"
    voice_spec_versions ||--o{ character_voice_bindings : "references"
    voice_spec_versions ||--o{ execution_instances : "references"
    voice_spec_versions ||--o{ sound_cues : "references"
    works ||--o{ episodes : "references"
```

