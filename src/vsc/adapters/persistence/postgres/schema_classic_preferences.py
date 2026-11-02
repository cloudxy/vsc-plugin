"""Personal media favorites are separate from creative adoption and project revisions."""
from sqlalchemy import Column, Boolean, Integer, ForeignKey, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID

CLASSIC_PREFERENCE_TABLES = ('classic_media_favorites',)


def declare_classic_preferences(project_table, ref, uid, stamp):
    favorites = project_table('classic_media_favorites', *ref('media_items', 'media_id'),
        Column('identity_id', UUID(as_uuid=False), ForeignKey('access_identities.id', ondelete='RESTRICT'), nullable=False),
        Column('active', Boolean, nullable=False), Column('version', Integer, nullable=False), stamp(),
        UniqueConstraint('project_id', 'identity_id', 'media_id'), CheckConstraint('version > 0', name='version'))
    Index('ix_classic_media_favorites_identity_active', favorites.c.identity_id, favorites.c.project_id, favorites.c.active)
    return {favorites.name: favorites}


CLASSIC_PREFERENCE_GUARD_DDL = '''
CREATE FUNCTION vsc_classic_favorite_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'favorite history must be retained' USING ERRCODE='23514'; END IF;
 IF ROW(NEW.id,NEW.project_id,NEW.identity_id,NEW.media_id,NEW.created_at) IS DISTINCT FROM ROW(OLD.id,OLD.project_id,OLD.identity_id,OLD.media_id,OLD.created_at) OR NEW.version<>OLD.version+1 THEN
  RAISE EXCEPTION 'favorite identity is fixed and version must advance once' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER classic_favorite_guard BEFORE UPDATE OR DELETE ON classic_media_favorites FOR EACH ROW EXECUTE FUNCTION vsc_classic_favorite_guard();
'''
