"""Typed organization and recoverable visibility; identities and evidence stay original."""
from sqlalchemy import Column, Text, Integer, DateTime, CheckConstraint, UniqueConstraint, Index

MANAGEMENT_IMMUTABLE = ()


def declare_management(project_table, ref, uid, stamp):
    folder=project_table('management_folders', *ref('management_folders','parent_id',nullable=True),
        Column('title',Text,nullable=False),Column('ordinal',Integer,nullable=False),stamp(),
        CheckConstraint('ordinal >= 0',name='ordinal'),CheckConstraint('parent_id IS NULL OR parent_id <> id',name='not_self'))
    Index('uq_management_folder_position',folder.c.project_id,folder.c.parent_id,folder.c.ordinal,unique=True,postgresql_nulls_not_distinct=True)
    tables=[folder]
    for name,target,field in [('object_folder_memberships','creative_objects','object_id'),('media_folder_memberships','media_items','media_id')]:
        tables.append(project_table(name,*ref(target,field),*ref('management_folders','folder_id'),UniqueConstraint('project_id',field)))
    for name,extra in [('management_project_states',()),('management_object_states',ref('creative_objects','object_id'))]:
        tables.append(project_table(name,*extra,Column('state',Text,nullable=False),Column('reason',Text,nullable=False),
            Column('actor',Text,nullable=False),Column('changed_at',DateTime(timezone=True),nullable=False),
            CheckConstraint("state IN ('active','trashed','purged')",name='state'),
            UniqueConstraint('project_id',*(['object_id'] if extra else []))))
    tables.append(project_table('management_canvas_states',*ref('creative_canvases','canvas_id'),
        Column('state',Text,nullable=False),Column('reason',Text,nullable=False),
        Column('actor',Text,nullable=False),Column('changed_at',DateTime(timezone=True),nullable=False),
        CheckConstraint("state IN ('active','trashed')",name='state'),UniqueConstraint('project_id','canvas_id')))
    tables.append(project_table('management_retention',Column('days',Integer),Column('actor',Text,nullable=False),stamp(),
        CheckConstraint('days IS NULL OR (days >= 1 AND days <= 36500)',name='days'),UniqueConstraint('project_id')))
    return {t.name:t for t in tables}
