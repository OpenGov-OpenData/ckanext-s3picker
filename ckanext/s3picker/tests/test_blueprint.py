from urllib.parse import parse_qs, unquote, urlparse

import pytest

PUBLIC = '/custom-downloads/county-a'
PRIVATE = '/custom-downloads/restricted'


def _body(response):
    return response.get_data(as_text=True)


@pytest.mark.usefixtures('with_plugins', 'indexed')
class TestPickerPage:

    def test_public_catalog_renders_for_anonymous(self, app):
        response = app.get(PUBLIC)
        assert response.status_code == 200
        body = _body(response)
        assert 'County A 2024 LiDAR' in body
        assert 'data-browse-url="/custom-downloads/county-a/browse"' in body
        assert '16 files' in body

    def test_unknown_catalog_is_404(self, app):
        assert app.get('/custom-downloads/nope').status_code == 404

    def test_private_catalog_redirects_anonymous_to_login(self, app):
        response = app.get(PRIVATE, follow_redirects=False)
        assert response.status_code == 302
        assert '/user/login' in response.headers['Location']

    def test_private_catalog_renders_for_logged_in_user(
            self, app, user_with_token):
        response = app.get(PRIVATE, headers=user_with_token['headers'])
        assert response.status_code == 200
        assert '2 files' in _body(response)

    def test_summary_separates_stats_from_instructions(self, app):
        body = _body(app.get(PUBLIC))
        assert '<p class="s3picker-stats">16 files \u00b7 4.0 KB total</p>' in body
        assert '<p class="s3picker-hint">Select files or folders' in body

    @pytest.mark.ckan_config('ckanext.s3picker.max_files_per_request', '12000')
    def test_summary_uses_thousands_separators(self, app):
        body = _body(app.get(PUBLIC))
        assert 'Up to 12,000 files per request' in body
        assert '12000' not in body.replace('data-max-files="12000"', '')

    def test_page_tells_the_script_whether_the_catalog_is_private(self, app):
        assert 'data-private="false"' in _body(app.get(PUBLIC))

    def test_private_page_is_marked_private(self, app, user_with_token):
        response = app.get(PRIVATE, headers=user_with_token['headers'])
        assert 'data-private="true"' in _body(response)


@pytest.mark.usefixtures('with_plugins', 's3picker_tables')
def test_unindexed_catalog_shows_notice(app):
    response = app.get(PUBLIC)
    assert response.status_code == 200
    assert 'has not been indexed yet' in _body(response)


@pytest.mark.usefixtures('with_plugins', 'indexed')
class TestBrowse:

    def test_root_listing(self, app):
        data = app.get(PUBLIC + '/browse').json
        assert data['path'] == ''
        assert [d['path'] for d in data['dirs']] == [
            'dem', 'metadata', 'odd_names', 'tiles']
        assert data['dirs'][-1]['file_count'] == 8
        assert [f['name'] for f in data['files']] == ['README.txt']
        assert data['has_more'] is False

    def test_paging(self, app):
        data = app.get(PUBLIC + '/browse?path=tiles/north&page_size=3').json
        assert data['total'] == 4
        assert len(data['files']) == 3
        assert data['has_more'] is True
        data = app.get(
            PUBLIC + '/browse?path=tiles/north&page_size=3&page=1').json
        assert [f['name'] for f in data['files']] == ['tile_004.laz']
        assert data['has_more'] is False

    def test_search(self, app):
        data = app.get(PUBLIC + '/browse?q=dem_').json
        assert sorted(f['path'] for f in data['files']) == [
            'dem/dem_1m.tif', 'dem/dem_2m.tif']
        assert data['total_size'] == 75

    def test_unknown_folder(self, app):
        assert app.get(PUBLIC + '/browse?path=nope').status_code == 404

    def test_private_requires_login(self, app, user_with_token):
        assert app.get(PRIVATE + '/browse').status_code == 403
        response = app.get(PRIVATE + '/browse',
                           headers=user_with_token['headers'])
        assert response.status_code == 200
        assert len(response.json['files']) == 2


@pytest.mark.usefixtures('with_plugins', 'indexed')
class TestMatches:

    def test_returns_all_matches(self, app):
        data = app.get(PUBLIC + '/matches?q=tile_00').json
        assert data['total'] == 4
        assert data['total_size'] == 1000
        assert data['max_files'] == 1000
        assert sorted(f['path'] for f in data['files']) == [
            'tiles/north/tile_001.laz', 'tiles/north/tile_002.laz',
            'tiles/north/tile_003.laz', 'tiles/north/tile_004.laz']

    def test_ids_can_be_downloaded(self, app):
        files = app.get(PUBLIC + '/matches?q=dem_').json['files']
        response = app.post(PUBLIC + '/download',
                            json={'files': [f['id'] for f in files]})
        assert response.status_code == 200
        assert response.json['count'] == 2

    @pytest.mark.ckan_config('ckanext.s3picker.max_files_per_request', '3')
    def test_over_limit_returns_totals_only(self, app):
        data = app.get(PUBLIC + '/matches?q=tile_').json
        assert (data['total'], data['max_files'], data['files']) == (8, 3, [])

    def test_no_matches(self, app):
        data = app.get(PUBLIC + '/matches?q=zzz').json
        assert (data['total'], data['files']) == (0, [])

    def test_search_text_required(self, app):
        assert app.get(PUBLIC + '/matches').status_code == 400
        assert app.get(PUBLIC + '/matches?q=%20').status_code == 400

    def test_unknown_catalog(self, app):
        assert app.get('/custom-downloads/nope/matches?q=a').status_code == 404

    def test_private_requires_login(self, app, user_with_token):
        assert app.get(PRIVATE + '/matches?q=secret').status_code == 403
        response = app.get(PRIVATE + '/matches?q=secret',
                           headers=user_with_token['headers'])
        assert response.status_code == 200
        assert response.json['total'] == 2

    def test_other_catalogs_files_are_not_matched(self, app):
        assert app.get(PUBLIC + '/matches?q=secret').json['total'] == 0


@pytest.mark.usefixtures('with_plugins', 'indexed')
class TestDownload:

    def test_folders_and_files(self, app):
        readme_id = app.get(PUBLIC + '/browse').json['files'][0]['id']
        response = app.post(PUBLIC + '/download', json={
            'files': [readme_id], 'folders': ['tiles/south/deep']})
        assert response.status_code == 200
        data = response.json
        assert data['count'] == 3
        assert data['total_size'] == 20
        assert 'expires_in' not in data
        paths = sorted(f['path'] for f in data['files'])
        assert paths == ['README.txt', 'tiles/south/deep/tile_201.laz',
                         'tiles/south/deep/tile_202.laz']
        for f in data['files']:
            url = urlparse(f['url'])
            assert url.scheme in ('http', 'https')
            assert url.path == PUBLIC + '/file/' + f['path']
        assert 'X-Amz-' not in _body(response)
        assert 'lidar-test-bucket' not in _body(response)

    def test_overlapping_selection_is_deduplicated(self, app):
        response = app.post(PUBLIC + '/download', json={
            'folders': ['tiles', 'tiles/south', '/tiles/north/']})
        assert response.json['count'] == 8

    def test_empty_selection(self, app):
        response = app.post(PUBLIC + '/download', json={})
        assert response.status_code == 400
        assert response.json['error'] == 'No files selected.'

    def test_invalid_payload(self, app):
        response = app.post(PUBLIC + '/download', json={'files': 'abc'})
        assert response.status_code == 400

    @pytest.mark.ckan_config('ckanext.s3picker.max_files_per_request', '3')
    def test_limit(self, app):
        response = app.post(PUBLIC + '/download', json={'folders': ['tiles']})
        assert response.status_code == 400
        assert 'contains 8 files' in response.json['error']

    def test_get_not_allowed(self, app):
        # CKAN 2.9 renders MethodNotAllowed as a 404 page.
        assert app.get(PUBLIC + '/download').status_code in (404, 405)

    def test_private_requires_login(self, app, user_with_token):
        payload = {'folders': ['']}
        assert app.post(PRIVATE + '/download', json=payload).status_code == 403
        response = app.post(PRIVATE + '/download', json=payload,
                            headers=user_with_token['headers'])
        assert response.status_code == 200
        assert response.json['count'] == 2


@pytest.mark.usefixtures('with_plugins', 'indexed')
class TestFileRedirect:

    def _get(self, app, url, **kwargs):
        return app.get(url, follow_redirects=False, **kwargs)

    def test_redirects_to_short_lived_presigned_url(self, app):
        response = self._get(app, PUBLIC + '/file/dem/dem_1m.tif')
        assert response.status_code == 302
        cache_control = response.headers['Cache-Control']
        assert 'no-store' in cache_control
        assert 'public' not in cache_control
        location = urlparse(response.headers['Location'])
        params = parse_qs(location.query)
        assert location.path.endswith('/county-a/2024/dem/dem_1m.tif')
        assert params['X-Amz-Expires'] == ['60']
        assert params['response-content-disposition'] == [
            'attachment; filename="dem_1m.tif"']

    def test_urls_from_download_endpoint_resolve(self, app):
        data = app.post(PUBLIC + '/download', json={
            'folders': ['odd_names']}).json
        assert data['count'] == 3
        for f in data['files']:
            response = self._get(app, urlparse(f['url']).path)
            assert response.status_code == 302, f['path']
            location = unquote(urlparse(response.headers['Location']).path)
            assert location.endswith('/county-a/2024/' + f['path'])

    @pytest.mark.ckan_config('ckanext.s3picker.presigned_url_expiry', '300')
    def test_expiry_is_configurable(self, app):
        response = self._get(app, PUBLIC + '/file/README.txt')
        params = parse_qs(urlparse(response.headers['Location']).query)
        assert params['X-Amz-Expires'] == ['300']

    def test_unindexed_paths_are_404(self, app):
        assert self._get(app, PUBLIC + '/file/nope.laz').status_code == 404
        assert self._get(app, PUBLIC + '/file/dem').status_code == 404
        # Exists in the bucket, but outside this catalog.
        assert self._get(
            app, PUBLIC + '/file/../../unrelated/other.laz').status_code == 404
        assert self._get(
            app, PUBLIC + '/file/secret_001.laz').status_code == 404
        assert self._get(
            app, '/custom-downloads/nope/file/README.txt').status_code == 404

    def test_private_requires_login(self, app, user_with_token):
        url = PRIVATE + '/file/secret_001.laz'
        assert self._get(app, url).status_code == 403
        response = self._get(app, url, headers=user_with_token['headers'])
        assert response.status_code == 302
        assert 'restricted/secret_001.laz' in response.headers['Location']
