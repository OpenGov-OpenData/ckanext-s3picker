import ast
import json

import ckan.plugins as p
import ckan.plugins.toolkit as tk

CATALOGS = 'ckanext.s3picker.catalogs'
DEFAULT_BUCKET = 'ckanext.s3picker.default_bucket'
URL_EXPIRY = 'ckanext.s3picker.presigned_url_expiry'
MAX_FILES = 'ckanext.s3picker.max_files_per_request'
DRIVER_OPTIONS = 'ckanext.s3picker.driver_options'

CLOUDSTORAGE_REQUIRED = (
    'ckanext.cloudstorage.driver',
    'ckanext.cloudstorage.driver_options',
    'ckanext.cloudstorage.container_name',
)


def _parse_dict(raw, key):
    # JSON first so `true`/`false` work; Python literal for parity with
    # ckanext.cloudstorage.driver_options.
    try:
        value = json.loads(raw)
    except ValueError:
        try:
            value = ast.literal_eval(raw)
        except (ValueError, SyntaxError) as e:
            raise RuntimeError('{0} is not valid JSON or a Python dict '
                               'literal: {1}'.format(key, e))
    if not isinstance(value, dict):
        raise RuntimeError('{0} must be a dict'.format(key))
    return value


def _normalize(slug, entry, default_bucket):
    if not isinstance(entry, dict):
        raise RuntimeError('{0}: catalog "{1}" must be a dict'.format(
            CATALOGS, slug))
    if 'prefix' not in entry:
        raise RuntimeError('{0}: catalog "{1}" is missing "prefix"'.format(
            CATALOGS, slug))
    bucket = entry.get('bucket') or default_bucket
    if not bucket:
        raise RuntimeError(
            '{0}: catalog "{1}" has no "bucket" and {2} is not set'.format(
                CATALOGS, slug, DEFAULT_BUCKET))
    prefix = entry['prefix'] or ''
    if prefix and not prefix.endswith('/'):
        prefix += '/'
    return {
        'slug': slug,
        'bucket': bucket,
        'prefix': prefix,
        'private': bool(entry.get('private', False)),
        'title': entry.get('title') or slug,
        'description': entry.get('description') or '',
    }


def get_catalogs():
    raw = tk.config.get(CATALOGS)
    if not raw:
        return {}
    default_bucket = tk.config.get(DEFAULT_BUCKET)
    return {
        slug: _normalize(slug, entry, default_bucket)
        for slug, entry in _parse_dict(raw, CATALOGS).items()
    }


def get_catalog(slug):
    catalog = get_catalogs().get(slug)
    if catalog is None:
        raise tk.ObjectNotFound('Unknown catalog: {0}'.format(slug))
    return catalog


def url_expiry():
    # Short by default: URLs are signed when a user follows a CKAN file link,
    # and S3 keeps streaming a download that started before expiry.
    return tk.asint(tk.config.get(URL_EXPIRY, 60))


def max_files_per_request():
    return tk.asint(tk.config.get(MAX_FILES, 1000))


def _validate_driver_options(options):
    if bool(options.get('key')) != bool(options.get('secret')):
        raise RuntimeError(
            '{0} must set both "key" and "secret", or neither (to use the '
            'default AWS credential chain).'.format(DRIVER_OPTIONS))
    return options


def get_driver_options(config=None):
    """s3picker's own S3 options, or None to fall back to cloudstorage's."""
    raw = (config or tk.config).get(DRIVER_OPTIONS)
    if not raw:
        return None
    return _validate_driver_options(_parse_dict(raw, DRIVER_OPTIONS))


def check_required_config(config):
    if get_driver_options(config) is None:
        for key in CLOUDSTORAGE_REQUIRED:
            if config.get(key) is None:
                raise RuntimeError(
                    'Set {0}, or configure ckanext-cloudstorage so its '
                    'credentials can be reused; required configuration '
                    'option {1} not found.'.format(DRIVER_OPTIONS, key))
        if not p.plugin_loaded('cloudstorage'):
            raise RuntimeError(
                'Set {0}, or enable the "cloudstorage" plugin in '
                'ckan.plugins so its credentials can be reused.'.format(
                    DRIVER_OPTIONS))
    if not config.get(CATALOGS):
        raise RuntimeError(
            'Required configuration option {0} not found.'.format(CATALOGS))
    get_catalogs()
