import logging
import posixpath

from sqlalchemy import (BigInteger, Column, DateTime, Index, Integer,
                        UnicodeText, UniqueConstraint, func, or_, text, true)

try:
    from sqlalchemy.orm import declarative_base
except ImportError:  # SQLAlchemy < 1.4 (CKAN 2.9)
    from sqlalchemy.ext.declarative import declarative_base

import ckan.model.meta as meta
from ckan.model.types import make_uuid

log = logging.getLogger(__name__)

Base = declarative_base()


class S3PickerFile(Base):
    __tablename__ = 's3picker_file'
    __table_args__ = (
        UniqueConstraint('catalog', 's3_key', name='s3picker_file_catalog_key'),
        Index('s3picker_file_catalog_parent', 'catalog', 'parent_path'),
    )

    id = Column(UnicodeText, primary_key=True, default=make_uuid)
    catalog = Column(UnicodeText, nullable=False)
    s3_bucket = Column(UnicodeText, nullable=False)
    s3_key = Column(UnicodeText, nullable=False)
    relative_path = Column(UnicodeText, nullable=False)
    parent_path = Column(UnicodeText, nullable=False)
    name = Column(UnicodeText, nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    last_modified = Column(DateTime)
    checksum = Column(UnicodeText)

    def as_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'path': self.relative_path,
            'size': self.size_bytes,
            'last_modified': (self.last_modified.isoformat()
                              if self.last_modified else None),
        }


class S3PickerDir(Base):
    __tablename__ = 's3picker_dir'
    __table_args__ = (
        UniqueConstraint('catalog', 'path', name='s3picker_dir_catalog_path'),
        Index('s3picker_dir_catalog_parent', 'catalog', 'parent_path'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog = Column(UnicodeText, nullable=False)
    path = Column(UnicodeText, nullable=False)
    parent_path = Column(UnicodeText)
    name = Column(UnicodeText, nullable=False)
    file_count = Column(Integer, nullable=False, default=0)
    total_size = Column(BigInteger, nullable=False, default=0)

    def as_dict(self):
        return {
            'name': self.name,
            'path': self.path,
            'file_count': self.file_count,
            'size': self.total_size,
        }


SETUP_LOCK_ID = 0x5333504B  # arbitrary, unique to this extension


def setup():
    # Every web worker runs this at startup; serialize them so two workers
    # can't both see "no table" and race on CREATE TABLE.
    with meta.engine.begin() as conn:
        if conn.dialect.name == 'postgresql':
            conn.execute(text('SELECT pg_advisory_xact_lock(:id)'),
                         {'id': SETUP_LOCK_ID})
        Base.metadata.create_all(bind=conn, checkfirst=True)


def _escape_like(value):
    return (value.replace('\\', '\\\\')
                 .replace('%', '\\%')
                 .replace('_', '\\_'))


def _ancestors(parent_path):
    yield ''
    if parent_path:
        parts = parent_path.split('/')
        for i in range(1, len(parts) + 1):
            yield '/'.join(parts[:i])


def replace_catalog(catalog, bucket, prefix, objects, chunk_size=1000):
    """Replace every index row for `catalog` in a single transaction.

    Returns (file_count, dir_count).
    """
    session = meta.Session
    dirs = {'': [0, 0]}
    file_count = 0
    batch = []
    try:
        session.query(S3PickerFile).filter_by(catalog=catalog).delete(
            synchronize_session=False)
        session.query(S3PickerDir).filter_by(catalog=catalog).delete(
            synchronize_session=False)

        for obj in objects:
            relative_path = obj['key'][len(prefix):]
            parent_path = posixpath.dirname(relative_path)
            batch.append({
                'id': make_uuid(),
                'catalog': catalog,
                's3_bucket': bucket,
                's3_key': obj['key'],
                'relative_path': relative_path,
                'parent_path': parent_path,
                'name': posixpath.basename(relative_path),
                'size_bytes': obj['size'],
                'last_modified': obj.get('last_modified'),
                'checksum': obj.get('etag'),
            })
            for path in _ancestors(parent_path):
                totals = dirs.setdefault(path, [0, 0])
                totals[0] += 1
                totals[1] += obj['size']
            file_count += 1
            if len(batch) >= chunk_size:
                session.bulk_insert_mappings(S3PickerFile, batch)
                batch = []
        if batch:
            session.bulk_insert_mappings(S3PickerFile, batch)

        session.bulk_insert_mappings(S3PickerDir, [
            {
                'catalog': catalog,
                'path': path,
                'parent_path': posixpath.dirname(path) if path else None,
                'name': posixpath.basename(path),
                'file_count': count,
                'total_size': size,
            }
            for path, (count, size) in dirs.items()
        ])
        session.commit()
    except Exception:
        session.rollback()
        raise
    return file_count, len(dirs)


def get_file(catalog, s3_key):
    return meta.Session.query(S3PickerFile).filter_by(
        catalog=catalog, s3_key=s3_key).first()


def get_dir(catalog, path):
    return meta.Session.query(S3PickerDir).filter_by(
        catalog=catalog, path=path).first()


def list_dir(catalog, path, page, page_size):
    """One page of a folder's children: sub-folders first, then files."""
    dir_q = (meta.Session.query(S3PickerDir)
             .filter_by(catalog=catalog, parent_path=path)
             .order_by(S3PickerDir.name))
    file_q = (meta.Session.query(S3PickerFile)
              .filter_by(catalog=catalog, parent_path=path)
              .order_by(S3PickerFile.name))
    n_dirs = dir_q.count()
    n_files = file_q.count()
    offset = page * page_size

    dirs = []
    if offset < n_dirs:
        dirs = dir_q.offset(offset).limit(page_size).all()
    remaining = page_size - len(dirs)
    files = []
    if remaining > 0:
        files = (file_q.offset(max(0, offset - n_dirs))
                 .limit(remaining).all())
    return {
        'dirs': [d.as_dict() for d in dirs],
        'files': [f.as_dict() for f in files],
        'total': n_dirs + n_files,
    }


def _search_query(catalog, q):
    # Shared by search() and search_matches() so the visible results and
    # "select all matches" always cover the same files.
    pattern = '%{0}%'.format(_escape_like(q))
    return (meta.Session.query(S3PickerFile)
            .filter(S3PickerFile.catalog == catalog,
                    S3PickerFile.relative_path.ilike(pattern, escape='\\')))


def _totals(query):
    return query.with_entities(
        func.count(S3PickerFile.id),
        func.coalesce(func.sum(S3PickerFile.size_bytes), 0)).one()


def search(catalog, q, page, page_size):
    query = _search_query(catalog, q)
    total, total_size = _totals(query)
    files = (query.order_by(S3PickerFile.relative_path)
             .offset(page * page_size).limit(page_size).all())
    return {
        'dirs': [],
        'files': [f.as_dict() for f in files],
        'total': total,
        'total_size': int(total_size),
    }


def search_matches(catalog, q, limit):
    """All matches for `q`, or just the totals when there are more than `limit`.

    Returns (total, total_size, rows).
    """
    query = _search_query(catalog, q)
    total, total_size = _totals(query)
    rows = []
    if 0 < total <= limit:
        rows = query.order_by(S3PickerFile.relative_path).all()
    return total, int(total_size), rows


def selection_query(catalog, file_ids, folder_paths):
    """Query for the union of explicit files and everything under folders."""
    conditions = []
    if file_ids:
        conditions.append(S3PickerFile.id.in_(list(file_ids)))
    for path in folder_paths:
        if path == '':
            conditions.append(true())
        else:
            conditions.append(S3PickerFile.relative_path.like(
                _escape_like(path) + '/%', escape='\\'))
    query = meta.Session.query(S3PickerFile).filter(
        S3PickerFile.catalog == catalog)
    if not conditions:
        return query.filter(S3PickerFile.id.is_(None))
    return query.filter(or_(*conditions)).order_by(S3PickerFile.relative_path)
