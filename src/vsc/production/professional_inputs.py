"""Fixed professional source references; approval remains with original consumers."""
from copy import deepcopy
import re
import uuid
from vsc.assets.resource_service import ResourceError

KIND_TYPES={
    'screenplay':{'vsc.screenplay','screenplay','script','script-workspace'},
    'shot_plan':{'vsc.shot_plan','shot-plan'},
    'scene_state':{'vsc.scene_state','scene-state'},
    'sequence_links':{'vsc.sequence_links','sequence-links'},
    'sound_plan':{'vsc.sound_plan','sound-plan','vsc.sound_cue_sheet','sound-cue-sheet','creative-relations'},
    'creative_rules':{'vsc.creative_brief','creative-brief','vsc.creative_rules','creative-rules'},
    'continuity':{'vsc.continuity_plan','continuity-plan'},
    'workflow':{'intelligent-workflow-state'},
}

def _identifier(value):
    try:return str(uuid.UUID(value))
    except (TypeError,ValueError,AttributeError):
        raise ResourceError('专业来源需要固定版本标识','professional_input_invalid')

def _sha(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):
        raise ResourceError('专业来源需要固定摘要','professional_input_invalid')
    return value

def normalize_professional_inputs(value,*,allow_workflow=False):
    if not isinstance(value,list) or len(value)>24:
        raise ResourceError('专业依据需要有界的固定版本列表','professional_input_invalid')
    result=[];seen=set()
    for row in value:
        if not isinstance(row,dict) or set(row)!={'id','sha256','kind'} or row['kind'] not in KIND_TYPES or (row['kind']=='workflow' and not allow_workflow):
            raise ResourceError('专业依据类型或字段无效','professional_input_invalid')
        fixed={'id':_identifier(row['id']),'sha256':_sha(row['sha256']),'kind':row['kind']}
        if fixed['id'] in seen:raise ResourceError('同一专业来源只能固定一次','professional_input_duplicate')
        seen.add(fixed['id']);result.append(fixed)
    return result

def normalize_source_workflow(value):
    fields={'version_id','artifact_id','artifact_sha256','state_sha256','unit_key'}
    if not isinstance(value,dict) or set(value)!=fields:
        raise ResourceError('制作来源需要完整固定的分集流程版本','professional_workflow_invalid')
    result=deepcopy(value)
    for field in ('version_id','artifact_id'):result[field]=_identifier(result[field])
    for field in ('artifact_sha256','state_sha256'):result[field]=_sha(result[field])
    if not isinstance(result['unit_key'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',result['unit_key']):
        raise ResourceError('制作来源需要固定的镜头单元','professional_workflow_invalid')
    return result

def script_texts(document,*,include_speakers=False):
    """Extract declared text only; never infer speech timing or approve coverage."""
    if isinstance(document,str):return [document] if document.strip() else []
    if not isinstance(document,dict):return []
    for key in ('script_text','body','text'):
        if isinstance(document.get(key),str) and document[key].strip():return [document[key]]
    result=[]
    for scene in document.get('scenes',[]):
        if not isinstance(scene,dict):continue
        for key in ('lines','units','actions','dialogue','silence'):
            for row in scene.get(key,[]):
                if isinstance(row,str) and row.strip():result.append(row)
                elif isinstance(row,dict) and isinstance(row.get('text'),str) and row['text'].strip():
                    speaker=row.get('speaker')
                    result.append((str(speaker)+'：' if include_speakers and key=='dialogue' and speaker else '')+row['text'])
    return result
