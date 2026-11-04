"""Asset card commands compose original objects, artifact projections and media registrations."""
import json
from sqlalchemy import select,insert,update,func,and_,case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from vsc.assets.resource_service import ResourceError,Conflict
from . import schema as S
from .values import checked_id,new_id,clean

class AssetCardsRepository:
    def __init__(self,store):self.store=store
    def __getattr__(self,name):return getattr(self.store,name)

    def _legacy_preview(self,conn,p,asset_id,asset_kind,usability_cache):
        # This is a card-level display hint, never a form or production binding.
        # Prefer an identity master over secondary views; within a role prefer
        # the newest current selection, then use IDs as a deterministic tie-break.
        roles={"character": ("identity_face", "costume"),
               "location": ("location_master", "location_view"),
               "style": ("style_reference",), "costume": ("costume",),
               "prop": ("prop",), "object": ("prop",), "creature": ("prop",),
               "vehicle": ("prop",), "plant": ("prop",)}.get(asset_kind, ())
        if not roles:return None
        slots, current, candidates, decisions, media = (S.binding_slots, S.current_bindings,
            S.binding_candidates, S.binding_decisions, S.media_items)
        lifecycle=(select(S.media_lifecycle_decisions.c.outcome).where(
            S.media_lifecycle_decisions.c.project_id==p,S.media_lifecycle_decisions.c.media_id==media.c.id)
            .order_by(S.media_lifecycle_decisions.c.decision_sequence.desc()).limit(1).scalar_subquery())
        available=select(S.blob_locations.c.id).where(S.blob_locations.c.blob_id==media.c.blob_id,
            S.blob_locations.c.available.is_(True)).exists()
        query=(select(slots.c.id.label('slot_id'), slots.c.role, slots.c.slot_key,
                      slots.c.variant_spec_id, candidates.c.id.label('candidate_id'),
                      candidates.c.media_id, candidates.c.spec_version_id,
                      decisions.c.id.label('decision_id'), decisions.c.decision_sequence)
            .select_from(slots.join(current,and_(current.c.project_id==slots.c.project_id,current.c.slot_id==slots.c.id))
                .join(candidates,and_(candidates.c.project_id==current.c.project_id,candidates.c.slot_id==current.c.slot_id,candidates.c.id==current.c.candidate_id))
                .join(decisions,and_(decisions.c.project_id==current.c.project_id,decisions.c.slot_id==current.c.slot_id,decisions.c.candidate_id==current.c.candidate_id,decisions.c.id==current.c.decision_id))
                .join(media,and_(media.c.project_id==candidates.c.project_id,media.c.id==candidates.c.media_id)))
            .where(slots.c.project_id==p,slots.c.target_object_id==asset_id,
                   slots.c.role.in_(roles),media.c.modality=='image',decisions.c.outcome=='select',
                   func.coalesce(lifecycle,'')!='deprecate',available)
            .order_by(case({role:index for index,role in enumerate(roles)},value=slots.c.role),
                      decisions.c.decision_sequence.desc(),slots.c.id,candidates.c.id))
        for row in conn.execute(query).mappings():
            # _usable checks current rights, lifecycle, locations, technical
            # checks and upstream library/copy restrictions, including expiry.
            if row['spec_version_id'] and not self._artifact_approved(conn,p,row['spec_version_id']):continue
            key=(row['media_id'],row['role'])
            if key not in usability_cache:
                _,gaps=self._usable(conn,p,*key)
                usability_cache[key]=not gaps
            if not usability_cache[key]:continue
            return dict(media_id=row['media_id'],source='current_binding',slot_id=row['slot_id'],
                        slot_key=row['slot_key'],role=row['role'],variant_spec_id=row['variant_spec_id'],
                        candidate_id=row['candidate_id'],decision_id=row['decision_id'])
        return None

    def _asset_card(self,conn,p,asset_id,actor=None,include_preview=False,usability_cache=None):
        from .project_management import hidden_object_ids
        asset=self._one(conn,S.asset_identities,p,asset_id)
        if asset_id in hidden_object_ids(conn,p):raise ResourceError('此资产已移入回收','object_recycled',409)
        obj=self._one(conn,S.creative_objects,p,asset_id)
        state=conn.execute(select(S.asset_card_states).where(S.asset_card_states.c.project_id==p,S.asset_card_states.c.asset_id==asset_id)).mappings().first()
        rows=[]
        for form in conn.execute(select(S.asset_card_forms).where(S.asset_card_forms.c.project_id==p,S.asset_card_forms.c.asset_id==asset_id).order_by(S.asset_card_forms.c.created_at,S.asset_card_forms.c.id)).mappings():
            fixed=self._one(conn,S.asset_card_form_versions,p,form['current_version_id']);spec=self._one(conn,S.asset_spec_versions,p,fixed['spec_id']);artifact=self._one(conn,S.artifact_versions,p,spec['artifact_id']);doc=json.loads(bytes(artifact['document']));body=next((x for x in doc.get('asset_specs',[]) if x['id']==spec['id']),{})
            history=[dict(v) for v in conn.execute(select(S.asset_card_form_versions.c.id,S.asset_card_form_versions.c.version,S.asset_card_form_versions.c.form_name,S.asset_card_form_versions.c.media_id).where(S.asset_card_form_versions.c.project_id==p,S.asset_card_form_versions.c.form_id==form['id']).order_by(S.asset_card_form_versions.c.version.desc())).mappings()]
            rows.append(dict(form,version_id=fixed['id'],version=fixed['version'],spec_id=spec['id'],description=body.get('description',''),media_id=fixed['media_id'],voice_spec_id=fixed['voice_spec_id'],history=history))
        # Existing identities remain visible before the first working card is saved.
        has_working_card=bool(rows)
        if not rows:
            seen=set()
            for spec in conn.execute(select(S.asset_spec_versions).join(S.artifact_versions,and_(S.artifact_versions.c.project_id==p,S.artifact_versions.c.id==S.asset_spec_versions.c.artifact_id)).where(S.asset_spec_versions.c.project_id==p,S.asset_spec_versions.c.asset_id==asset_id).order_by(S.artifact_versions.c.created_at.desc())).mappings():
                if spec['variant_key'] in seen:continue
                seen.add(spec['variant_key']);document=json.loads(bytes(self._one(conn,S.artifact_versions,p,spec['artifact_id'])['document']));body=next((x for x in document.get('asset_specs',[]) if x.get('id')==spec['id']),{})
                rows.append(dict(form_key=spec['variant_key'],name=spec['variant_key'],version_id=None,version=0,spec_id=spec['id'],description=body.get('description',''),media_id=None,voice_spec_id=None,history=[]))
        favorite=conn.execute(select(S.asset_card_favorites.c.active).where(S.asset_card_favorites.c.project_id==p,S.asset_card_favorites.c.asset_id==asset_id,S.asset_card_favorites.c.actor==actor)).scalar_one_or_none() if actor else False
        preview=self._legacy_preview(conn,p,asset_id,asset['asset_kind'],usability_cache if usability_cache is not None else {}) if include_preview and not has_working_card else None
        return dict(id=asset_id,name=obj['title'] or obj['display_code'],asset_kind=asset['asset_kind'],revision=state['revision'] if state else 0,forms=rows,favorite=bool(favorite),preview=preview)

    def list_asset_cards(self,p,query='',asset_kind='',offset=0,limit=24,actor=None,favorites=False,include_object=False):
        from .project_management import hidden_object_ids
        with self.engine.connect().execution_options(vsc_readonly_preview=True) as conn:
            project=self._project(conn,p);hidden=hidden_object_ids(conn,p)
            q=select(S.asset_identities.c.id).join(S.creative_objects,and_(S.creative_objects.c.project_id==p,S.creative_objects.c.id==S.asset_identities.c.id)).where(S.asset_identities.c.project_id==p,S.asset_identities.c.id.not_in(hidden))
            if query:q=q.where(S.creative_objects.c.title.ilike('%'+query+'%'))
            if asset_kind:q=q.where(S.asset_identities.c.asset_kind.in_(['prop','object']) if include_object else S.asset_identities.c.asset_kind==asset_kind)
            if favorites:q=q.join(S.asset_card_favorites,and_(S.asset_card_favorites.c.project_id==p,S.asset_card_favorites.c.asset_id==S.asset_identities.c.id,S.asset_card_favorites.c.actor==actor,S.asset_card_favorites.c.active))
            total=conn.scalar(select(func.count()).select_from(q.subquery()));ids=conn.execute(q.order_by(S.creative_objects.c.title,S.asset_identities.c.id).offset(offset).limit(limit)).scalars()
            usability_cache={}
            return clean(dict(items=[self._asset_card(conn,p,i,actor,include_preview=True,usability_cache=usability_cache) for i in ids],total=total,offset=offset,next_offset=offset+limit if offset+limit<total else None,revision=project['revision']))

    def get_asset_card(self,p,asset_id,actor=None):
        with self.engine.connect().execution_options(vsc_readonly_preview=True) as conn:return clean(dict(self._asset_card(conn,p,checked_id(asset_id),actor,include_preview=True),project_revision=self._project(conn,p)['revision']))

    def _save_asset_card(self,conn,project,payload,actor):
        p=project['id'];identifier=payload.get('asset_id');prior=None
        if identifier:
            prior=self._asset_card(conn,p,checked_id(identifier))
            if prior['asset_kind']!=payload['asset_kind']:raise ResourceError('资产身份类型不能通过编辑改变')
        if payload['base_revision']!=(prior['revision'] if prior else 0):raise Conflict('资产卡已有更新，本机输入保留','asset_card_conflict')
        if not identifier:identifier=self._create_object(conn,project,dict(kind='asset',asset_kind=payload['asset_kind'],display_code='AS-'+new_id()[:8],title=payload['name']))['id']
        else:conn.execute(update(S.creative_objects).where(S.creative_objects.c.project_id==p,S.creative_objects.c.id==identifier).values(title=payload['name']))
        conn.execute(pg_insert(S.asset_card_states).values(project_id=p,id=new_id(),asset_id=identifier,revision=payload['base_revision']+1).on_conflict_do_update(index_elements=['project_id','asset_id'],set_={'revision':payload['base_revision']+1}))
        result=[]
        for supplied in payload['forms']:
            form=conn.execute(select(S.asset_card_forms).where(S.asset_card_forms.c.project_id==p,S.asset_card_forms.c.asset_id==identifier,S.asset_card_forms.c.form_key==supplied['form_key'])).mappings().first()
            if supplied.get('base_version_id')!=(form['current_version_id'] if form else None):raise Conflict('资产形态已有新版本','asset_form_conflict')
            form_id=form['id'] if form else new_id();spec_id=new_id();voice_id=supplied.get('voice_spec_id');media=self._media(conn,p,supplied['media_id']) if supplied.get('media_id') else None
            if media and media['modality']!=('audio' if payload['asset_kind']=='voice' else 'image'):raise ResourceError('形态素材类型不匹配')
            spec=dict(id=spec_id,asset_id=identifier,variant_key=supplied['form_key'],description=supplied.get('description',''))
            doc={'asset_specs':[spec]}
            if payload['asset_kind']=='voice':
                voice_id=new_id();doc['voice_specs']=[dict(id=voice_id,voice_id=identifier,reference_media_id=media['id'] if media else None,diction=supplied.get('voice_details',{}).get('diction',{'description':supplied.get('description','')}),post_chain=supplied.get('voice_details',{}).get('post_chain',{}))]
            elif voice_id:
                if payload['asset_kind']!='character':raise ResourceError('只有角色可以绑定声线')
                self._one(conn,S.voice_spec_versions,p,voice_id);doc['voice_bindings']=[dict(character_id=identifier,voice_spec_id=voice_id)]
            self._create_artifact(conn,project,dict(artifact_key='asset-card:'+identifier+':'+supplied['form_key'],artifact_type='asset-bible',document=doc,object_ids=[identifier],**doc))
            if not form:conn.execute(insert(S.asset_card_forms).values(project_id=p,id=form_id,asset_id=identifier,form_key=supplied['form_key'],name=supplied['name']))
            v=self._one(conn,S.asset_card_form_versions,p,form['current_version_id'])['version']+1 if form else 1;version_id=new_id()
            row=dict(project_id=p,id=version_id,form_id=form_id,version=v,spec_id=spec_id,asset_name=payload['name'],form_name=supplied['name'],media_id=media['id'] if media else None,blob_id=media['blob_id'] if media else None,blob_sha256=media['sha256'] if media else None,voice_spec_id=voice_id,created_by=actor)
            conn.execute(insert(S.asset_card_form_versions).values(**row));conn.execute(update(S.asset_card_forms).where(S.asset_card_forms.c.project_id==p,S.asset_card_forms.c.id==form_id).values(name=supplied['name'],current_version_id=version_id));result.append(dict(form_key=supplied['form_key'],version_id=version_id,spec_id=spec_id,media_id=row['media_id']))
        return dict(id=identifier,asset_revision=payload['base_revision']+1,forms=result)

    def save_asset_card(self,p,payload,actor,**kw):return self._mutate(p,'save_asset_card',payload,actor=actor,callback=lambda c,pr:self._save_asset_card(c,pr,payload,actor),**kw)

    def favorite_asset_card(self,p,payload,actor,**kw):
        def work(conn,project):
            self._one(conn,S.asset_identities,p,payload['asset_id'])
            conn.execute(pg_insert(S.asset_card_favorites).values(project_id=p,id=new_id(),asset_id=payload['asset_id'],actor=actor,active=payload['active']).on_conflict_do_update(index_elements=['project_id','asset_id','actor'],set_={'active':payload['active']}))
            return dict(asset_id=payload['asset_id'],active=payload['active'])
        return self._mutate(p,'favorite_asset_card',payload,actor=actor,callback=work,**kw)

    def reference_asset_card(self,p,payload,actor,**kw):
        def work(conn,project):
            card=self._asset_card(conn,p,payload['asset_id']);outputs=[]
            if card['revision']!=payload['asset_revision']:raise Conflict('源资产已更新，请先读回形态')
            for episode in payload['episode_ids']:
                self._one(conn,S.episodes,p,episode);key='asset:'+card['id'];prior=conn.execute(select(S.episode_assets).where(S.episode_assets.c.project_id==p,S.episode_assets.c.episode_id==episode,S.episode_assets.c.asset_key==key)).mappings().first()
                old={r['form_key']:r for r in conn.execute(select(S.episode_asset_forms).where(S.episode_asset_forms.c.project_id==p,S.episode_asset_forms.c.episode_asset_id==prior['id'])).mappings()} if prior else {}
                forms=[dict(form_key=f['form_key'],name=old[f['form_key']]['name'] if f['form_key'] in old else f['name'],base_version_id=old.get(f['form_key'],{}).get('current_version_id'),source_asset_id=card['id'],spec_id=f['spec_id'],media_id=f['media_id']) for f in card['forms'] if f.get('spec_id')]
                outputs.append(self.save_episode_asset(p,dict(episode_id=episode,**({'id':prior['id']} if prior else {}),base_revision=prior['revision'] if prior else 0,asset_key=key,name=prior['name'] if prior else card['name'],asset_kind=card['asset_kind'],forms=forms),actor=actor,expected_revision=project['revision'],idempotency_key='asset-card-episode',_transaction=(conn,project)))
            return dict(items=outputs)
        return self._mutate(p,'reference_asset_card',payload,actor=actor,callback=work,**kw)

    def copy_asset_card(self,p,payload,actor,**kw):
        source=checked_id(payload['source_project_id'])
        def work(conn,project):
            original=self._asset_card(conn,source,payload['source_asset_id'])
            requested=payload['form_version_ids'];forms=[];media_map={};voice_map={}
            def copied_media(mid):
                if not mid:return None
                if mid in media_map:return media_map[mid]
                from .copy_lineage import assert_copy_source
                item=self._media(conn,source,mid);rights=assert_copy_source(self.store,conn,source,mid)
                if rights and rights['outcome'] not in {'owned','licensed','unknown'}:raise ResourceError('来源素材权利已限制，不可复制')
                location=next((l for l in item['locations'] if l['available']),None)
                if not location:raise ResourceError('源素材没有可用副本')
                copied=self._register_media(conn,project,dict(item,id=new_id(),storage=location['storage'],object_key=location['object_key'],rights=rights['outcome'] if rights else 'unknown',rights_scope=rights['scope'] if rights else {'purposes':[]},rights_expires_at=rights['expires_at'] if rights else None,source={'kind':'project-asset-copy','content':{'source_project_id':source,'source_asset_id':original['id'],'source_media_id':mid,'sha256':item['sha256']}}),actor)
                media_map[mid]=copied['id'];return copied['id']
            def copied_voice(vid):
                if not vid:return None
                if vid in voice_map:return voice_map[vid]
                voice=self._one(conn,S.voice_spec_versions,source,vid);identity=self._one(conn,S.creative_objects,source,voice['voice_id'])
                saved=self._save_asset_card(conn,project,dict(name=identity['title'] or '复制声线',asset_kind='voice',base_revision=0,forms=[dict(form_key='master',name='默认声线',base_version_id=None,description='从源人物固定声线复制',media_id=copied_media(voice['reference_media_id']),voice_details=dict(diction=voice['diction'],post_chain=voice['post_chain']))]),actor)
                copied=self._one(conn,S.asset_card_form_versions,p,saved['forms'][0]['version_id'])['voice_spec_id'];voice_map[vid]=copied;return copied
            for version_id in requested:
                fixed=self._one(conn,S.asset_card_form_versions,source,version_id);form=self._one(conn,S.asset_card_forms,source,fixed['form_id'])
                if form['asset_id']!=original['id']:raise ResourceError('复制形态不属于源资产')
                spec=self._one(conn,S.asset_spec_versions,source,fixed['spec_id']);doc=json.loads(bytes(self._one(conn,S.artifact_versions,source,spec['artifact_id'])['document']));body=next(x for x in doc['asset_specs'] if x['id']==spec['id'])
                forms.append(dict(form_key=form['form_key'],name=fixed['form_name'],base_version_id=None,description=body.get('description',''),media_id=copied_media(fixed['media_id']),voice_spec_id=copied_voice(fixed['voice_spec_id']) if original['asset_kind']=='character' else None,voice_details=dict(self._one(conn,S.voice_spec_versions,source,fixed['voice_spec_id'])) if original['asset_kind']=='voice' and fixed['voice_spec_id'] else {}))
            result=self._save_asset_card(conn,project,dict(name=payload.get('name') or original['name'],asset_kind=original['asset_kind'],base_revision=0,forms=forms),actor)
            for before,after in zip(requested,result['forms']):conn.execute(insert(S.asset_card_copy_sources).values(project_id=p,id=new_id(),target_form_version_id=after['version_id'],source_project_id=source,source_form_version_id=before,created_by=actor))
            return dict(result,copied_voice_count=len(voice_map))
        from .copy_lineage import source_projects_for_copy
        with self.engine.connect() as c:related=source_projects_for_copy(c,source)
        return self._mutate(p,'copy_asset_card',payload,actor=actor,callback=work,_related_projects=related,**kw)
