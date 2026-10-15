import pytest

import ckan.plugins.toolkit as tk

from ckanext.s3picker import config as s3config


@pytest.mark.usefixtures('ckan_config')
class TestCatalogs:

    def test_catalogs_from_test_ini(self):
        catalogs = s3config.get_catalogs()
        assert catalogs['county-a'] == {
            'slug': 'county-a',
            'bucket': 'lidar-test-bucket',
            'prefix': 'county-a/2024/',
            'private': False,
            'title': 'County A 2024 LiDAR',
            'description': '',
        }
        assert catalogs['restricted']['private'] is True
        assert catalogs['restricted']['title'] == 'restricted'

    @pytest.mark.ckan_config(
        'ckanext.s3picker.catalogs',
        "{'x': {'prefix': 'some/path', 'bucket': 'other', 'private': True}}")
    def test_python_literal_and_prefix_normalization(self):
        catalog = s3config.get_catalog('x')
        assert catalog['prefix'] == 'some/path/'
        assert catalog['bucket'] == 'other'
        assert catalog['private'] is True

    @pytest.mark.ckan_config('ckanext.s3picker.catalogs',
                             '{"all": {"prefix": ""}}')
    def test_empty_prefix_means_whole_bucket(self):
        assert s3config.get_catalog('all')['prefix'] == ''

    def test_unknown_catalog(self):
        with pytest.raises(tk.ObjectNotFound):
            s3config.get_catalog('nope')

    @pytest.mark.ckan_config('ckanext.s3picker.catalogs',
                             '{"x": {"bucket": "b"}}')
    def test_missing_prefix(self):
        with pytest.raises(RuntimeError, match='missing "prefix"'):
            s3config.get_catalogs()

    @pytest.mark.ckan_config('ckanext.s3picker.default_bucket', '')
    @pytest.mark.ckan_config('ckanext.s3picker.catalogs',
                             '{"x": {"prefix": "a/"}}')
    def test_missing_bucket(self):
        with pytest.raises(RuntimeError, match='has no "bucket"'):
            s3config.get_catalogs()

    @pytest.mark.ckan_config('ckanext.s3picker.catalogs', 'not a dict')
    def test_invalid_value(self):
        with pytest.raises(RuntimeError, match='not valid JSON'):
            s3config.get_catalogs()

    def test_limits_have_defaults(self):
        assert s3config.url_expiry() == 60
        assert s3config.max_files_per_request() == 1000


@pytest.mark.usefixtures('with_plugins')
class TestRequiredConfig:

    def _config(self, **overrides):
        config = dict(tk.config)
        config.update(overrides)
        return config

    def test_valid(self):
        s3config.check_required_config(self._config())

    def test_missing_cloudstorage_key(self):
        config = self._config()
        del config['ckanext.cloudstorage.driver_options']
        with pytest.raises(RuntimeError, match='driver_options'):
            s3config.check_required_config(config)

    def test_missing_catalogs(self):
        config = self._config()
        del config['ckanext.s3picker.catalogs']
        with pytest.raises(RuntimeError, match='catalogs'):
            s3config.check_required_config(config)

    def test_own_driver_options_make_cloudstorage_optional(self, monkeypatch):
        monkeypatch.setattr(s3config.p, 'plugin_loaded', lambda name: False)
        config = self._config(**{
            'ckanext.s3picker.driver_options':
                '{"key": "k", "secret": "s", "region_name": "us-west-2"}'})
        for key in s3config.CLOUDSTORAGE_REQUIRED:
            del config[key]
        s3config.check_required_config(config)

    def test_driver_options_without_keys_is_valid(self):
        config = self._config(**{
            'ckanext.s3picker.driver_options': '{"region_name": "us-west-2"}'})
        s3config.check_required_config(config)

    def test_driver_options_key_without_secret(self):
        config = self._config(**{
            'ckanext.s3picker.driver_options': '{"key": "k"}'})
        with pytest.raises(RuntimeError, match='both "key" and "secret"'):
            s3config.check_required_config(config)

    def test_cloudstorage_plugin_not_loaded(self, monkeypatch):
        monkeypatch.setattr(s3config.p, 'plugin_loaded', lambda name: False)
        with pytest.raises(RuntimeError, match='"cloudstorage" plugin'):
            s3config.check_required_config(self._config())
