import boto3
import pytest
from moto import mock_aws

import ckan.model.meta as meta
import ckan.plugins.toolkit as tk

from ckanext.s3picker import aws
from ckanext.s3picker import model as s3model

BUCKET = 'lidar-test-bucket'

# Matches the catalogs configured in test.ini.
OBJECTS = {
    'county-a/2024/': 0,  # folder marker, must be skipped
    'county-a/2024/README.txt': 10,
    'county-a/2024/tiles/north/tile_001.laz': 100,
    'county-a/2024/tiles/north/tile_002.laz': 200,
    'county-a/2024/tiles/north/tile_003.laz': 300,
    'county-a/2024/tiles/north/tile_004.laz': 400,
    'county-a/2024/tiles/south/tile_101.laz': 1000,
    'county-a/2024/tiles/south/tile_102.laz': 2000,
    'county-a/2024/tiles/south/deep/tile_201.laz': 5,
    'county-a/2024/tiles/south/deep/tile_202.laz': 5,
    'county-a/2024/dem/dem_1m.tif': 50,
    'county-a/2024/dem/dem_2m.tif': 25,
    'county-a/2024/odd_names/100%_done.laz': 1,
    'county-a/2024/odd_names/a_b.laz': 1,
    'county-a/2024/odd_names/axb.laz': 1,
    'county-a/2024/metadata/report.pdf': 7,
    'county-a/2024/metadata/boundary.geojson': 3,
    'restricted/secret_001.laz': 11,
    'restricted/secret_002.laz': 12,
    'unrelated/other.laz': 99,
}


@pytest.fixture
def s3_bucket():
    with mock_aws():
        aws._client.cache_clear()
        client = boto3.client(
            's3', region_name='us-east-1',
            aws_access_key_id='testing', aws_secret_access_key='testing')
        client.create_bucket(Bucket=BUCKET)
        for key, size in OBJECTS.items():
            client.put_object(Bucket=BUCKET, Key=key, Body=b'x' * size)
        yield client
    aws._client.cache_clear()


@pytest.fixture
def s3picker_tables(clean_db):
    s3model.setup()
    meta.Session.query(s3model.S3PickerFile).delete()
    meta.Session.query(s3model.S3PickerDir).delete()
    meta.Session.commit()


@pytest.fixture
def indexed(s3_bucket, s3picker_tables):
    for slug, prefix in (('county-a', 'county-a/2024/'),
                         ('restricted', 'restricted/')):
        s3model.replace_catalog(
            slug, BUCKET, prefix,
            aws.iter_bucket_objects(s3_bucket, BUCKET, prefix))
    return s3_bucket


@pytest.fixture
def user_with_token():
    from ckan.tests import factories
    user = factories.User()
    token = tk.get_action('api_token_create')(
        {'user': user['name'], 'ignore_auth': True},
        {'user': user['name'], 'name': 'test'})['token']
    return {'user': user, 'headers': {'Authorization': token}}
