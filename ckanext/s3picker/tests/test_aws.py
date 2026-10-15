from urllib.parse import parse_qs, urlparse

import pytest

from ckanext.s3picker import aws
from ckanext.s3picker.tests.fixtures import BUCKET


@pytest.mark.parametrize('host,expected', [
    (None, None),
    ('', None),
    ('s3.amazonaws.com', None),
    ('s3.us-west-2.amazonaws.com', None),
    ('minio.example.org', 'https://minio.example.org'),
    ('http://localhost:9000', 'http://localhost:9000'),
])
def test_endpoint_url(host, expected):
    assert aws._endpoint_url(host) == expected


@pytest.mark.usefixtures('with_plugins')
def test_credentials_come_from_cloudstorage():
    assert aws.credentials() == {
        'key': 'testing',
        'secret': 'testing',
        'region': 'us-east-1',
        'endpoint_url': None,
    }


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config(
    'ckanext.s3picker.driver_options',
    '{"key": "lidar-key", "secret": "lidar-secret", "region_name": "us-west-2",'
    ' "host": "s3.us-west-2.amazonaws.com"}')
def test_own_driver_options_take_precedence():
    assert aws.credentials() == {
        'key': 'lidar-key',
        'secret': 'lidar-secret',
        'region': 'us-west-2',
        'endpoint_url': None,
    }


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config('ckanext.s3picker.driver_options',
                         "{'region_name': 'us-west-2'}")
def test_driver_options_without_keys_use_default_chain():
    creds = aws.credentials()
    assert (creds['key'], creds['secret'], creds['region']) == (
        None, None, 'us-west-2')


def test_iter_bucket_objects_skips_folder_markers(s3_bucket):
    objects = list(aws.iter_bucket_objects(s3_bucket, BUCKET, 'restricted/'))
    assert sorted(o['key'] for o in objects) == [
        'restricted/secret_001.laz', 'restricted/secret_002.laz']
    assert {o['size'] for o in objects} == {11, 12}

    keys = [o['key'] for o in
            aws.iter_bucket_objects(s3_bucket, BUCKET, 'county-a/2024/')]
    assert 'county-a/2024/' not in keys
    assert len(keys) == 16


def test_generate_presigned_url(s3_bucket):
    client = aws._client('testing', 'testing', 'us-east-1', None)
    url = aws.generate_presigned_url(
        client, BUCKET, 'county-a/2024/dem/dem_1m.tif', 600)
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.path.endswith('/county-a/2024/dem/dem_1m.tif')
    assert params['X-Amz-Expires'] == ['600']
    assert params['response-content-disposition'] == [
        'attachment; filename="dem_1m.tif"']
