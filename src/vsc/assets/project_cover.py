"""Display-only project covers do not grant production or rights approval."""
from io import BytesIO
import warnings
from vsc.assets.resource_service import ResourceError

MAX_COVER_BYTES = 5 * 1024 * 1024


class ProjectCoverServiceMixin:
    def get_project_cover(self, project_id):
        return self.store.get_project_cover(project_id)

    def _check_project_cover_media(self, media):
        if media['modality'] != 'image':
            raise ResourceError('项目封面需要图像', 'project_cover_image_required')
        if not 0 < media['size_bytes'] <= MAX_COVER_BYTES:
            raise ResourceError('项目封面最大 5 MiB', 'project_cover_too_large', 413)
        if self.storage is None:
            raise ResourceError('设置封面需要受控媒体存储', 'storage_unavailable', 409)
        content = None
        for location in media.get('locations', []):
            if location.get('available') and location.get('storage') == 'local':
                try:
                    content = self.storage.read(location['object_key'], media['sha256'])
                    break
                except (OSError, ResourceError):
                    continue
        if content is None:
            raise ResourceError('封面的固定图像字节不可读取', 'project_cover_media_unavailable', 409)
        if not 0 < len(content) <= MAX_COVER_BYTES:
            raise ResourceError('项目封面最大 5 MiB', 'project_cover_too_large', 413)
        try:
            from PIL import Image
        except ImportError as exc:
            raise ResourceError('封面图像解码依赖未安装', 'image_decoder_unavailable', 503) from exc
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    image.verify()
                with Image.open(BytesIO(content)) as image:
                    image.load()
        except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ResourceError('封面必须是可完整解码的真实图像', 'project_cover_invalid_image') from exc

    def set_project_cover(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {'media_id'} or payload['media_id'] is not None and not isinstance(payload['media_id'], str):
            raise ResourceError('封面设置需要同项目媒体 ID，清除时传 null', 'invalid_project_cover')
        return self.store.set_project_cover(project_id, payload, check_media=self._check_project_cover_media, **kw)
