import threading

import pytest
from sqlalchemy import inspect

import ckan.model.meta as meta

from ckanext.s3picker import aws
from ckanext.s3picker import model as s3model
from ckanext.s3picker.tests.fixtures import BUCKET


def _paths(query):
    return [row.relative_path for row in query]


@pytest.mark.usefixtures('with_plugins', 'clean_db')
def test_setup_is_safe_when_workers_start_concurrently():
    meta.Session.remove()
    s3model.Base.metadata.drop_all(bind=meta.engine)
    workers = 6
    barrier = threading.Barrier(workers)
    errors = []

    def start_worker():
        barrier.wait()
        try:
            s3model.setup()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=start_worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    tables = inspect(meta.engine).get_table_names()
    assert {'s3picker_file', 's3picker_dir'} <= set(tables)


@pytest.mark.usefixtures('indexed')
class TestIndex:

    def test_root_totals(self):
        root = s3model.get_dir('county-a', '')
        assert root.file_count == 16
        assert root.total_size == 4108
        assert root.parent_path is None

    def test_nested_folder_totals(self):
        south = s3model.get_dir('county-a', 'tiles/south')
        assert (south.file_count, south.total_size) == (4, 3010)
        assert south.parent_path == 'tiles'
        assert south.name == 'south'

    def test_rebuild_is_idempotent_and_isolated(self, s3_bucket):
        files, dirs = s3model.replace_catalog(
            'county-a', BUCKET, 'county-a/2024/',
            aws.iter_bucket_objects(s3_bucket, BUCKET, 'county-a/2024/'))
        assert files == 16
        assert dirs == 8
        count = meta.Session.query(s3model.S3PickerFile).filter_by(
            catalog='county-a').count()
        assert count == 16
        assert s3model.get_dir('restricted', '').file_count == 2

    def test_rebuild_removes_deleted_objects(self, s3_bucket):
        s3_bucket.delete_object(Bucket=BUCKET,
                                Key='county-a/2024/dem/dem_1m.tif')
        s3model.replace_catalog(
            'county-a', BUCKET, 'county-a/2024/',
            aws.iter_bucket_objects(s3_bucket, BUCKET, 'county-a/2024/'))
        assert s3model.get_dir('county-a', 'dem').file_count == 1
        assert s3model.get_dir('county-a', '').file_count == 15

    def test_list_dir_folders_first(self):
        result = s3model.list_dir('county-a', '', page=0, page_size=100)
        assert [d['name'] for d in result['dirs']] == [
            'dem', 'metadata', 'odd_names', 'tiles']
        assert [f['name'] for f in result['files']] == ['README.txt']
        assert result['total'] == 5

    def test_list_dir_pagination_spans_folders_and_files(self):
        pages = [s3model.list_dir('county-a', 'tiles/south', page=p,
                                  page_size=2) for p in range(2)]
        assert [d['name'] for d in pages[0]['dirs']] == ['deep']
        assert [f['name'] for f in pages[0]['files']] == ['tile_101.laz']
        assert pages[1]['dirs'] == []
        assert [f['name'] for f in pages[1]['files']] == ['tile_102.laz']

    def test_search_escapes_wildcards(self):
        result = s3model.search('county-a', '100%', 0, 50)
        assert [f['path'] for f in result['files']] == [
            'odd_names/100%_done.laz']
        result = s3model.search('county-a', 'a_b', 0, 50)
        assert [f['path'] for f in result['files']] == ['odd_names/a_b.laz']

    def test_search_reports_total_size(self):
        result = s3model.search('county-a', 'tile_00', 0, 2)
        assert result['total_size'] == 1000

    def test_search_matches_returns_all_rows(self):
        total, size, rows = s3model.search_matches('county-a', 'tile_', 100)
        assert (total, size) == (8, 4010)
        assert len(rows) == 8
        assert _paths(rows) == sorted(_paths(rows))

    def test_search_matches_omits_rows_over_limit(self):
        total, size, rows = s3model.search_matches('county-a', 'tile_', 3)
        assert (total, size, rows) == (8, 4010, [])

    def test_search_matches_escapes_wildcards_and_scopes_catalog(self):
        _, _, rows = s3model.search_matches('county-a', '100%', 100)
        assert _paths(rows) == ['odd_names/100%_done.laz']
        assert s3model.search_matches('county-a', 'secret', 100)[0] == 0
        assert s3model.search_matches('restricted', 'secret', 100)[0] == 2

    def test_search_matches_no_results(self):
        assert s3model.search_matches('county-a', 'zzz', 100) == (0, 0, [])

    def test_search_is_case_insensitive_and_scoped(self):
        result = s3model.search('county-a', 'SECRET', 0, 50)
        assert result['total'] == 0
        result = s3model.search('county-a', 'TILE_00', 0, 2)
        assert result['total'] == 4
        assert len(result['files']) == 2

    def test_selection_folder_expansion(self):
        query = s3model.selection_query('county-a', [], ['tiles/south'])
        assert _paths(query) == [
            'tiles/south/deep/tile_201.laz',
            'tiles/south/deep/tile_202.laz',
            'tiles/south/tile_101.laz',
            'tiles/south/tile_102.laz',
        ]

    def test_selection_folder_prefix_is_not_partial_match(self):
        query = s3model.selection_query('county-a', [], ['tiles/sou'])
        assert query.count() == 0

    def test_selection_root_and_files(self):
        assert s3model.selection_query('county-a', [], ['']).count() == 16
        readme = s3model.list_dir('county-a', '', 0, 100)['files'][0]
        query = s3model.selection_query('county-a', [readme['id']], ['dem'])
        assert sorted(_paths(query)) == [
            'README.txt', 'dem/dem_1m.tif', 'dem/dem_2m.tif']

    def test_selection_ignores_other_catalogs(self):
        secret_id = s3model.list_dir('restricted', '', 0, 10)['files'][0]['id']
        assert s3model.selection_query('county-a', [secret_id], []).count() == 0

    def test_empty_selection(self):
        assert s3model.selection_query('county-a', [], []).count() == 0
