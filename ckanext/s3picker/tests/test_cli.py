import pytest

import ckan.plugins.toolkit as tk
from ckan.cli.cli import ckan
from ckan.tests import factories

from ckanext.s3picker import model as s3model


def _custom_download_resources(dataset_id):
    pkg = tk.get_action('package_show')(
        {'ignore_auth': True}, {'id': dataset_id})
    return [r for r in pkg['resources'] if r['format'] == 'Custom Download']


@pytest.mark.usefixtures('with_plugins', 's3_bucket', 's3picker_tables')
class TestBuildIndex:

    def test_build_index(self, cli):
        result = cli.invoke(
            ckan, ['s3picker', 'build-index', '--catalog', 'county-a'])
        assert result.exit_code == 0, result.output
        assert 'Indexed 16 files in 8 folders.' in result.output
        assert s3model.get_dir('county-a', 'tiles').file_count == 8

    def test_limit_indexes_first_files_only(self, cli):
        result = cli.invoke(ckan, [
            's3picker', 'build-index', '--catalog', 'county-a',
            '--limit', '3'])
        assert result.exit_code == 0, result.output
        assert 'Indexed 3 files' in result.output
        assert 'partial index' in result.output
        assert s3model.get_dir('county-a', '').file_count == 3

        result = cli.invoke(
            ckan, ['s3picker', 'build-index', '--catalog', 'county-a'])
        assert s3model.get_dir('county-a', '').file_count == 16

    def test_limit_must_be_positive(self, cli):
        result = cli.invoke(ckan, [
            's3picker', 'build-index', '--catalog', 'county-a',
            '--limit', '0'])
        assert result.exit_code != 0

    def test_unknown_catalog(self, cli):
        result = cli.invoke(
            ckan, ['s3picker', 'build-index', '--catalog', 'nope'])
        assert result.exit_code != 0
        assert 'Unknown catalog' in result.output


@pytest.mark.usefixtures('with_plugins', 'clean_db')
class TestLinkResource:

    def test_create_then_update(self, cli):
        dataset = factories.Dataset()
        args = ['s3picker', 'link-resource', '--catalog', 'county-a',
                '--dataset', dataset['name']]

        result = cli.invoke(ckan, args)
        assert result.exit_code == 0, result.output
        assert 'Created resource' in result.output
        resources = _custom_download_resources(dataset['id'])
        assert len(resources) == 1
        assert resources[0]['url'].endswith('/custom-downloads/county-a')
        assert resources[0]['name'] == 'County A 2024 LiDAR'

        result = cli.invoke(ckan, args + ['--name', 'Renamed'])
        assert result.exit_code == 0, result.output
        assert 'Updated resource' in result.output
        resources = _custom_download_resources(dataset['id'])
        assert len(resources) == 1
        assert resources[0]['name'] == 'Renamed'

    def test_separate_catalogs_get_separate_resources(self, cli):
        dataset = factories.Dataset()
        for slug in ('county-a', 'restricted'):
            result = cli.invoke(ckan, [
                's3picker', 'link-resource', '--catalog', slug,
                '--dataset', dataset['id']])
            assert result.exit_code == 0, result.output
        assert len(_custom_download_resources(dataset['id'])) == 2

    def test_unknown_dataset(self, cli):
        result = cli.invoke(ckan, [
            's3picker', 'link-resource', '--catalog', 'county-a',
            '--dataset', 'does-not-exist'])
        assert result.exit_code != 0
        assert 'Dataset not found' in result.output
