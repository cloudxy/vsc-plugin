"""Read-only projections of registered creation entries and bounded local documents.

Entry availability describes a checked navigation target, never provider readiness.
Only the seven production vendor routes are included; their documents stay references.
"""
from hashlib import sha256
import logging
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlencode

from vsc.assets.resource_service import ResourceError
from vsc.bootstrap import repository_root

LOGGER = logging.getLogger(__name__)
STAGES = ('adapt', 'script', 'direct', 'assets', 'produce', 'sound', 'post')
DISPLAY_STAGES = ('adapt', 'script', 'direct', 'assets', 'produce', 'post')
SOURCES = ('canvas', 'builtin', 'tutorial', 'vendor:inkos', 'vendor:openwrite',
           'vendor:openmontage', 'vendor:remotion')
DOCUMENT_LIMIT = 2 * 1024 * 1024
PROJECT_DEPENDENCY = '需要已有可编辑项目/工作区；服务、素材和成本在原工具确认'

# Explanatory metadata is deliberately explicit and tied to the original actions.
# stage, input, output, suitable, unsuitable, related tutorial
CANVAS_DETAILS = {
    'vsc-script': ('script', '创作目标、剧本或分镜材料', '可编辑文字与分镜建议', '补充目标并整理画布文字', '代替人工批准剧本', 'canvas'),
    'vsc-assets': ('assets', '固定参考与已选素材', '图像、音频或视频工作节点', '复用参考并准备素材候选', '未核对报价直接生成', 'canvas'),
    'vsc-direct': ('direct', '视频节点、镜头要求与模型偏好', '原运行的待审草稿', '运行前核对镜头与材料', '自动提交或批准生成任务', 'canvas'),
    'story-outline': ('adapt', '固定小说来源或故事创意', '可编辑故事大纲文字节点', '收敛故事因果与分集方向', '跳过改编边界确认', 'production'),
    'asset-extraction': ('assets', '引用的完整剧本', '人物、场景与道具清单文字节点', '制作前整理剧本资产', '自动批准资产或补造身份', 'production'),
    'asset-matching': ('assets', '本轮已选素材与待匹配要求', '可复用媒体节点与比较建议', '比较已有素材并复用', '缺少参考仍声称匹配成功', 'canvas'),
    'storyboard-upgrade': ('direct', '剧本节拍与已有分镜', '含时长、景别、机位、动作、对白的文字节点', '把分镜细化为可拍说明', '把文字建议当作生成成片', 'production'),
    'storyboard-grouping': ('direct', '已有分镜和连续动作', '按场景与机位组织的分镜组文字节点', '整理连续镜头的制作顺序', '改变已确认的故事事实', 'production'),
    'blocking-continuity': ('continuity', '前后镜头、人物站位与方向', '站位、方向和接续约束文字节点', '规划跨镜连续性', '替代实际成片连续性审查', 'production'),
    'storyboard-image': ('direct', '固定镜头描述与参考图', '图像工作节点及待确认运行', '准备分镜线稿候选', '未经报价确认直接生成', 'canvas'),
    'image-generation': ('produce', '提示词、参考与已选模型', '图片候选工作节点与原任务跟踪', '准备图片候选', '保证角色一致或自动采用候选', 'canvas'),
    'video-generation': ('produce', '提示词、参考与已选模型', '视频候选工作节点与原任务跟踪', '准备视频候选', '保证成片或跳过成本确认', 'canvas'),
    'async-media': ('produce', '固定图像、视频或声音输入', '媒体任务节点、查询与结果恢复', '准备和跟踪异步媒体任务', '重复提交状态未知的任务', 'canvas'),
    'storyboard-reuse': ('direct', '固定故事板文字或图像', '视频节点与来源依赖边', '复用故事板准备视频任务', '把故事板直接视为已完成视频', 'canvas'),
    'ai-mv-production': ('produce', '已上传音乐、歌词与角色场景参考', '可编辑分镜、节奏规划与媒体任务', '按音乐准备MV视觉与镜头', '缺材料时自动编造参考', 'canvas'),
    'sound-plan': ('sound', '场景、对白空间与声音目标', '声音计划或描述音频工作节点', '准备音乐、环境声和对白空间', '保证已生成或完成混音', 'production'),
}

# page, params, label (text-tool labels come from TOOLS), stages, input, output
BUILTIN_DETAILS = (
    ('text-tools', {'tool': 'novel'}, None, ('adapt', 'script'), '小说原文与改编边界', '梗概、人物、分集、场景或正文建议'),
    ('text-tools', {'tool': 'translation'}, None, ('script',), '原剧本、术语与目标语言', '当前集译文与术语建议'),
    ('text-tools', {'tool': 'scoring'}, None, ('script',), '剧本文本与固定评分标准', '类型、首卡分析与评分建议'),
    ('text-tools', {'tool': 'breakdown'}, None, ('direct',), '固定视频输入', '带时间码的观察与拉片稿'),
    ('text-tools', {'tool': 'qc'}, None, ('post',), '视频、字幕与所选检查项', '视频与字幕质检报告'),
    ('text-tools', {'tool': 'overseas'}, None, ('adapt', 'produce'), '固定源视频、理解稿与本地化目标', '视频理解、本地化建议与候选准备'),
    ('classic-production', {'kind': 'image'}, 'AI 图片生成', ('produce',), '提示词、参考图与已有剧集', '原图片制作流程的候选'),
    ('classic-production', {'kind': 'video'}, 'AI 视频生成', ('produce',), '提示词、参考素材与已有剧集', '原视频制作流程的候选'),
    ('intelligent-creation', {}, '智能创作', ('produce',), '原流程明确的材料与任务', '原智能工作流的方案与候选'),
    ('creative-tools', {'tool': 'segment_remake'}, '片段改写', ('produce',), '原视频与片段改写目标', '原工具的片段改写方案与候选'),
    ('creative-tools', {'tool': 'breakdown'}, '视频深度解析', ('direct',), '固定视频与分析目标', '原工具的视频深度解析结果'),
    ('marketing-studio', {}, '营销工作室（短剧宣发）', ('post',), '短剧宣发目标与已有素材', '营销方案与候选；内部Skill在原工具选取'),
    ('editing', {}, '剪辑工作台', ('post',), '已有素材、剧集与剪辑工作稿', '原剪辑预览与工作稿修补'),
    ('delivery', {}, '交付与审片', ('post',), '已有项目交付材料', '原交付检查与下载入口'),
)

# These describe how to apply the registered document, not a new Web executor.
METHOD_DETAILS = {
    'inkos-script-writing': ('小说、创意、大纲与改编边界', '可演动作、冲突、场次与剧本写作方法', '小说改编与短剧剧本', '以情节摘要替代场次'),
    'inkos-story-review': ('已有故事正文、题材与评审标准', '因果、人物动机与修订问题检查方法', '诊断现有故事与改编问题', '解析失败时判定正文不合格'),
    'novel-reviewer': ('章节正文、章纲与已有评审版本', '六域评审、证据与修订预览方法', '已有小说章节的审查润色', '未经确认覆盖原正文'),
    'dialoguequality': ('章节对白、角色档案与风格约束', '对白指纹、角色声音与AI味检查方法', '区分角色声音并检查台词失真', '只凭脱离上下文的几句对白定论'),
    'novel-creator': ('章纲、角色、伏笔与写前上下文', '章节草稿、人工确认与复评流程', '从既定章纲准备小说章节', '覆盖已有章节或跳过作者确认'),
    'inkos-storyboard': ('剧本节拍、空间关系与视觉限制', '景别、动作、连续性与图像提示词方法', '把叙事拆成可拍可画的分镜', '逐句机械拆镜或以散文代替分镜'),
    'inkos-interactive-film': ('互动故事前提、选择与制作约束', '剧情树、变量、可拍节点与可达结局方法', '互动影游或分支叙事', '只有措辞差异的伪分支'),
    'inkos-play-illustration': ('场景、人物、道具与已确认视觉事实', '保持世界与身份一致的插画方法', '戏剧场景与角色道具的视觉表达', '把游戏规则画成虚构界面'),
    'character-animation-qa': ('角色设计、绑定、动作时间线与渲染', '素材、动作、抽帧与最终视频质检方法', '检查角色动画预览与成片', '用静态结构通过代替视觉审查'),
    'create-video': ('视频描述、场景与时长目标', 'HeyGen视频生成、任务查询与取回方法', '由描述准备讲解或营销视频', '本页直接调用HeyGen或保证服务就绪'),
    'kling-official': ('Kling官方任务输入与所选能力', '官方图像、视频、语音或口型任务方法', '核对Kling官方API任务协议', '静默切换到其他Kling代理服务'),
    'video-understand': ('本地视频与抽帧、转写目标', 'ffmpeg抽帧和可选Whisper转写方法', '观察素材或复核候选内容', '声称本页自动分析或需要API密钥'),
    'music-to-video': ('音乐轨与可选图片或视频', '节拍分析、逐帧计划与HyperFrames合成方法', '以音乐节奏组织画面和剪辑', '无节奏音乐仍机械按节拍硬切'),
    'text-to-speech': ('对白文本、音色与语速要求', 'HeyGen Starfish独立语音生成方法', '准备旁白、配音或对白音频', '本页直接授权或调用语音服务'),
    'music': ('音乐提示词、歌词或组成计划', 'ElevenLabs音乐生成与计划方法', '准备BGM、器乐或歌曲', '把文档存在当作已取得API权限'),
    'video-edit': ('本地视频、音轨与剪切目标', 'ffmpeg剪切、拼接、变速、音轨与导出方法', '本地媒体剪辑与格式处理', '本页直接修改或覆盖媒体'),
    'ffmpeg': ('视频或音频与转换规格', '格式、尺寸、压缩、音轨与媒体检查方法', '为制作或Remotion准备媒体', '未经核对覆盖原素材'),
    'remotion-best-practices': ('Remotion制作目标与现有工程', 'Composition、媒体、预览与字幕方法索引', '查找Remotion制作与审阅方法', '把方法索引当Web渲染器'),
    'remotion-markup': ('React场景、媒体与帧时间线', '帧驱动动画、可编辑场景与媒体组织方法', '编写或修订Remotion画面', '依赖CSS时间动画保证渲染正确'),
    'remotion-captions': ('语音、字幕或已有SRT', '字幕JSON、转写、显示与动画方法', '处理Remotion字幕', '本页自动转写或导出字幕'),
    'remotion-studio': ('可运行Remotion工程与Composition', 'Studio启动和交互预览方法', '在原环境预览并人工调整', '把已安装文档当作Web预览已就绪'),
    'remotion-render': ('已确认Composition与导出规格', '视频、静帧与指定帧导出方法', '在原Remotion环境导出', '未经批准自动渲染或本页执行导出'),
}

TUTORIAL_DETAILS = {
    'production': (('adapt', 'script', 'direct', 'assets', 'produce', 'post'), '制作目标、剧本与跨集资产要求', '短剧制作流程与跨集资产复用指南'),
    'workspace': (('assets', 'produce'), '工作区、媒体或服务接入问题', '本机工作区、媒体与服务配置阅读指南'),
    'canvas': (('direct', 'assets', 'produce'), '画布、参考素材与当前操作目标', '画布创作、参考与操作指南'),
}


def identity(prefix, source, path):
    return prefix + sha256((source + '\0' + path).encode('utf-8')).hexdigest()


def _display(stages):
    mapped = {'produce' if s == 'sound' else 'assets' if s == 'continuity' else s for s in stages}
    return [s for s in DISPLAY_STAGES if s in mapped]


def _metadata(content):
    """Only scalar top-level metadata; YAML block markers are not summaries."""
    lines = content.splitlines()
    values = {}
    if lines and lines[0].strip() == '---':
        for line in lines[1:]:
            if line.strip() == '---':
                break
            if line.startswith((' ', '\t')) or ':' not in line:
                continue
            key, value = line.split(':', 1)
            value = value.strip().strip('\"\'')
            if value and value not in ('|', '>', '|-', '>-'):
                values[key.strip()] = value
    return values


def _relative(path):
    value = PurePosixPath(path)
    if (not path or value.is_absolute() or '..' in value.parts or '\\' in path
            or '\x00' in path or value.as_posix() != path):
        raise ResourceError('文档路径不在允许范围', 'document_forbidden', 403)
    return value


class CapabilityCatalog:
    """Server-owned roots and registrations; no request may supply either root."""
    def __init__(self, root=None, vendor_root=None, *, skills=None, tutorials=None,
                 vendor_routes=None):
        self.root = Path(root) if root is not None else repository_root()
        self.vendor_root = Path(vendor_root) if vendor_root is not None else self.root / 'vendor'
        self.skills = skills
        self.tutorials = tutorials
        self.vendor_routes = vendor_routes

    def _tutorials(self):
        if self.tutorials is None:
            from vsc.assets.discovery import TUTORIALS
            return TUTORIALS
        return self.tutorials

    def _routes(self):
        if self.vendor_routes is None:
            from tools.maintenance.vendor_skills import ROUTES
            return ROUTES
        return self.vendor_routes

    def _safe_path(self, source, path):
        relative = _relative(path)
        if source == 'tutorial':
            root = self.root.resolve()
            source_root = (root / 'docs/guide').resolve()
            candidate = (root / relative).resolve()
        elif source.startswith('vendor:'):
            root = self.vendor_root.resolve()  # The controlled mount itself may be a symlink.
            source_id = source.split(':', 1)[1]
            if source_id not in {s.split(':', 1)[1] for s in SOURCES if s.startswith('vendor:')}:
                raise ResourceError('文档路径不在允许范围', 'document_forbidden', 403)
            if not relative.parts or relative.parts[0] != source_id:
                raise ResourceError('文档路径不在允许范围', 'document_forbidden', 403)
            source_root = (root / source_id).resolve()
            candidate = (root / relative).resolve()
        else:
            raise ResourceError('文档不存在', 'document_not_found', 404)
        if (not source_root.is_relative_to(root) or not candidate.is_relative_to(source_root)
                or candidate == source_root):
            raise ResourceError('文档路径不在允许范围', 'document_forbidden', 403)
        return candidate

    def _read(self, source, path):
        try:
            candidate = self._safe_path(source, path)
            with candidate.open('rb') as stream:
                raw = stream.read(DOCUMENT_LIMIT + 1)
            if len(raw) > DOCUMENT_LIMIT:
                raise ResourceError('文档超过2 MiB读取上限', 'document_too_large', 413)
            content = raw.decode('utf-8')
            if not content.strip():
                raise ResourceError('文档暂时无法读取', 'document_unavailable', 503)
            return content, sha256(raw).hexdigest()
        except FileNotFoundError:
            raise ResourceError('文档不存在', 'document_not_found', 404) from None
        except (OSError, UnicodeError, RuntimeError):
            raise ResourceError('文档暂时无法读取', 'document_unavailable', 503) from None

    @staticmethod
    def _base(source, path, name, kind, stages=()):
        return dict(id=identity('cap_', source, path), source=source, path=path,
                    name=name, kind=kind, stages=_display(stages), origin_stages=list(stages),
                    task=None, version=None, sha256=None, inputs=[], outputs=[], suitable=[],
                    unsuitable=[], dependencies=[], installation={'state': 'unknown', 'document': 'not_applicable'},
                    status='unknown', status_reason='状态未确认', action=None, related_documents=[])

    def _related(self, key):
        tutorials = self._tutorials()
        if key not in tutorials:
            return []
        title, path = tutorials[key]
        return [dict(id=identity('doc_', 'tutorial', path), title=title, source='tutorial', path=path)]

    @staticmethod
    def _navigate(page, params):
        return dict(type='navigate', label='选择项目并打开原工具', requires_project=True,
                    target=dict(page=page, params=params), document_id=None)

    @staticmethod
    def _read_action(source, path):
        return dict(type='read', label='阅读原文', requires_project=False, target=None,
                    document_id=identity('doc_', source, path))

    def _canvas(self):
        if self.skills is None:
            from vsc.production.canvas_agent import SKILLS
            skills = SKILLS
        else:
            skills = self.skills
        items = []
        for key, skill in skills.items():
            detail = CANVAS_DETAILS.get(key)
            stages = (detail[0],) if detail else ()
            path = 'src/vsc/production/canvas_agent.py#SKILLS/' + key
            item = self._base('canvas', path, skill['name'], 'canvas_skill', stages)
            item.update(task=skill.get('description') or None, version=skill.get('version'),
                        dependencies=[PROJECT_DEPENDENCY], action=self._navigate('creative-canvas', {'skill': key}))
            source_skill = skill.get('source_skill', key)
            _relative(source_skill)
            candidate = (self.root / 'skills' / source_skill / 'SKILL.md').resolve()
            if not candidate.is_relative_to((self.root / 'skills').resolve()):
                raise ValueError('canvas source outside registered skill root')
            try:
                item['sha256'] = sha256(candidate.read_bytes()).hexdigest()
                item.update(status='entry_available', status_reason='可进入原画布；服务状态、素材和成本在原工具确认')
                item['installation']['document'] = 'present'
            except FileNotFoundError:
                item.update(status='dependency_required', status_reason='原核心Skill文档缺失；原工具仍需核对依赖')
                item['installation']['document'] = 'missing'
            if detail:
                item.update(inputs=[detail[1]], outputs=[detail[2]], suitable=[detail[3]],
                            unsuitable=[detail[4]], related_documents=self._related(detail[5]))
            items.append(item)
        return items

    def _builtin(self):
        from vsc.assets.text_tools import TOOLS
        items = []
        for page, params, label, stages, inputs, outputs in BUILTIN_DETAILS:
            path = 'page/' + page + ('?' + urlencode(params) if params else '')
            item = self._base('builtin', path, label or TOOLS[params['tool']]['label'], 'builtin_tool', stages)
            item.update(task=outputs, inputs=[inputs], outputs=[outputs],
                        suitable=['使用' + (label or TOOLS[params['tool']]['label']) + '的既有制作流程'],
                        unsuitable=['在能力中心自动创建、生成、保存或批准结果'], dependencies=[PROJECT_DEPENDENCY],
                        status='entry_available', status_reason='可进入原工具；服务状态、素材和成本在原工具确认',
                        action=self._navigate(page, dict(params)),
                        installation={'state': 'not_applicable', 'document': 'not_applicable'},
                        related_documents=self._related('production'))
            items.append(item)
        return items

    def _tutorial_items(self):
        items = []
        for key, (title, path) in self._tutorials().items():
            details = TUTORIAL_DETAILS.get(key)
            item = self._base('tutorial', path, title, 'tutorial', details[0] if details else ())
            self._document_metadata(item)
            if details:
                item.update(task=details[2], inputs=[details[1]], outputs=[details[2]],
                            suitable=['阅读' + title + '的本机操作与流程'], unsuitable=['以阅读代替配置、执行或人工批准'])
            item['installation']['state'] = 'not_applicable'
            items.append(item)
        return items

    def _vendor_registrations(self, source):
        source_id = source.split(':', 1)[1]
        grouped = {}
        for stage in STAGES:
            for registered_source, relative, readiness, purpose in self._routes().get(stage, ()):
                if registered_source != source_id:
                    continue
                path = source_id + '/' + relative
                row = grouped.setdefault(path, dict(path=path, stages=[], purposes=[], readiness=[]))
                if stage not in row['stages']:
                    row['stages'].append(stage)
                for field, value in (('purposes', purpose), ('readiness', readiness)):
                    if value and value not in row[field]:
                        row[field].append(value)
        return grouped

    def _document_metadata(self, item):
        try:
            content, digest = self._read(item['source'], item['path'])
        except ResourceError as error:
            if error.code != 'document_not_found':
                raise
            item.update(status='dependency_required', status_reason='已登记文档在本机缺失；可重试阅读，不能运行')
            item['installation']['document'] = 'missing'
        else:
            metadata = _metadata(content)
            if item['kind'] == 'external_method':
                item['name'] = metadata.get('name') or item['name']
            item.update(version=metadata.get('version'), sha256=digest, status='reference',
                        status_reason='仅供阅读的方法参考；文档存在不证明已安装或可在Web运行')
            item['installation']['document'] = 'present'
        item['action'] = self._read_action(item['source'], item['path'])

    def _vendor(self, source):
        items = []
        for path, registration in self._vendor_registrations(source).items():
            name = PurePosixPath(path).parent.name
            item = self._base(source, path, name, 'external_method', registration['stages'])
            self._document_metadata(item)
            details = METHOD_DETAILS.get(name)
            item.update(task='；'.join(registration['purposes']) or None,
                        dependencies=['仅提供原文阅读；运行环境和授权未在本页核对'] + registration['readiness'])
            if details:
                item.update(inputs=[details[0]], outputs=[details[1]], suitable=[details[2]], unsuitable=[details[3]])
            items.append(item)
        return items

    def capabilities(self, source=None):
        if source is not None and source not in SOURCES:
            raise ResourceError('能力来源无效', 'invalid_capability_source', 422)
        sources, items = [], []
        for selected in (source,) if source is not None else SOURCES:
            try:
                rows = (self._canvas() if selected == 'canvas' else self._builtin() if selected == 'builtin'
                        else self._tutorial_items() if selected == 'tutorial' else self._vendor(selected))
            except Exception as error:
                # Log classification only, never source text, absolute paths or credentials.
                LOGGER.warning('Capability source unavailable: source=%s type=%s', selected, type(error).__name__)
                sources.append(dict(id=selected, status='error', error=dict(
                    error='capability_source_unavailable', message='能力来源暂时无法读取')))
            else:
                sources.append(dict(id=selected, status='ok', error=None))
                items.extend(rows)
        failures = sum(s['status'] == 'error' for s in sources)
        status = 'unavailable' if failures == len(sources) else 'partial' if failures else 'ok'
        return dict(schema_version=1, status=status, sources=sources, items=items)

    def document(self, document_id):
        if not re.fullmatch(r'doc_[0-9a-f]{64}', document_id):
            raise ResourceError('文档不存在', 'document_not_found', 404)
        registrations = [('tutorial', path, title) for title, path in self._tutorials().values()]
        for source in SOURCES:
            if source.startswith('vendor:'):
                registrations.extend((source, path, PurePosixPath(path).parent.name)
                                     for path in self._vendor_registrations(source))
        for source, path, title in registrations:
            if identity('doc_', source, path) != document_id:
                continue
            content, digest = self._read(source, path)
            if source.startswith('vendor:'):
                title = _metadata(content).get('name') or title
            return dict(schema_version=1, id=document_id, title=title, source=source,
                        path=path, format='text/plain', content=content, sha256=digest)
        raise ResourceError('文档不存在', 'document_not_found', 404)
