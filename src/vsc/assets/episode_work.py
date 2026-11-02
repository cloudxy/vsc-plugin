"""Episode first-cut continuation over the existing batch and editor consumers."""
from vsc.assets.resource_service import ResourceError


class EpisodeWorkService:
    def _episode_work(self):
        from vsc.adapters.persistence.postgres.episode_work import EpisodeWorkRepository
        return EpisodeWorkRepository(self.store)

    def _first_cut_available(self):
        from vsc.post.edit_workspace import FirstCutRenderer
        return self.storage is not None and FirstCutRenderer().capabilities()['available']

    def intelligent_work_batch_status(self, p, batch_id):
        self.authorize_access(p, 'read')
        return self._episode_work().status(p, batch_id, renderer_available=self._first_cut_available())

    def advance_intelligent_work_batch(self, p, payload, actor):
        self.authorize_access(p, 'execute')
        if not isinstance(payload, dict) or set(payload) != {'batch_artifact_id'}:
            raise ResourceError('需要固定分集批次', 'invalid_intelligent_batch')
        return self._episode_work().advance(p, payload['batch_artifact_id'], renderer_available=self._first_cut_available(), actor=actor)

    def advance_episode_first_cuts(self, project_id=None):
        repository = self._episode_work()
        results = []
        cursors = getattr(self, '_episode_first_cut_scan', None)
        if cursors is None:
            cursors = self._episode_first_cut_scan = {}
        page = repository.pending(project_id, after=cursors.get(project_id))
        # Only an ephemeral keyset position: jobs and artifact receipts remain
        # the authority, and a restart can safely scan from the beginning.
        cursors[project_id] = page[-1]['scan_cursor'] if len(page) == 50 else None
        for row in page:
            try:
                results.append(repository.advance(row['project_id'], row['id'], renderer_available=self._first_cut_available()))
            except ResourceError:
                # Permission revocation, a hidden episode or one invalid batch
                # cannot prevent other previously authorized episodes advancing.
                continue
        return results
