import functools
import posixpath

import boto3
from botocore.config import Config

from ckanext.s3picker import config as s3config


def _endpoint_url(host):
    # Plain AWS hosts are left to boto3's region-aware resolution; a fixed
    # global endpoint breaks SigV4 presigning for non-us-east-1 buckets.
    if not host or host.rstrip('/').endswith('amazonaws.com'):
        return None
    if '://' in host:
        return host
    return 'https://{0}'.format(host)


@functools.lru_cache(maxsize=4)
def _client(key, secret, region, endpoint_url):
    return boto3.client(
        's3',
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name=region,
        endpoint_url=endpoint_url,
        config=Config(signature_version='s3v4'),
    )


def credentials():
    opts = s3config.get_driver_options()
    if opts is None:
        from ckanext.cloudstorage.storage import CloudStorage
        opts = CloudStorage().driver_options
    # A missing key/secret lets boto3 use its default credential chain
    # (env vars, shared profile, instance role).
    return {
        'key': opts.get('key') or None,
        'secret': opts.get('secret') or None,
        'region': opts.get('region_name') or opts.get('region'),
        'endpoint_url': _endpoint_url(opts.get('host')),
    }


def get_s3_client():
    c = credentials()
    return _client(c['key'], c['secret'], c['region'], c['endpoint_url'])


def iter_bucket_objects(client, bucket, prefix):
    paginator = client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('/'):
                continue
            yield {
                'key': obj['Key'],
                'size': obj['Size'],
                'last_modified': obj['LastModified'],
                'etag': obj.get('ETag', '').strip('"') or None,
            }


def generate_presigned_url(client, bucket, key, expires_in):
    filename = posixpath.basename(key).replace('"', '')
    return client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': bucket,
            'Key': key,
            'ResponseContentDisposition':
                'attachment; filename="{0}"'.format(filename),
        },
        ExpiresIn=expires_in,
    )
