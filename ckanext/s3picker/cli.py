import itertools

import click

import ckan.plugins.toolkit as tk

from ckanext.s3picker import aws
from ckanext.s3picker import config as s3config
from ckanext.s3picker import model as s3model

RESOURCE_FORMAT = 'Custom Download'


def picker_path(slug):
    return '/custom-downloads/{0}'.format(slug)


def _get_catalog(slug):
    try:
        return s3config.get_catalog(slug)
    except tk.ObjectNotFound as e:
        raise click.BadParameter(str(e), param_hint='--catalog')


@click.group()
def s3picker():
    """S3 picker management commands."""
    pass


@s3picker.command('build-index')
@click.option('--catalog', required=True,
              help='Catalog slug from ckanext.s3picker.catalogs')
@click.option('--limit', type=click.IntRange(min=1), default=None,
              help='Index only the first N files (in S3 key order), '
                   'e.g. for a quick test. Replaces any existing index.')
def build_index(catalog, limit):
    """Crawl a catalog's S3 bucket/prefix and rebuild its file index."""
    conf = _get_catalog(catalog)
    click.echo('Indexing s3://{0}/{1} for catalog "{2}"{3}...'.format(
        conf['bucket'], conf['prefix'], catalog,
        ' (first {0} files only)'.format(limit) if limit else ''))
    objects = aws.iter_bucket_objects(
        aws.get_s3_client(), conf['bucket'], conf['prefix'])
    if limit:
        objects = itertools.islice(objects, limit)
    files, dirs = s3model.replace_catalog(
        catalog, conf['bucket'], conf['prefix'], objects)
    click.secho('Indexed {0} files in {1} folders.'.format(files, dirs),
                fg='green')
    if limit and files == limit:
        click.secho('This is a partial index. Run again without --limit to '
                    'index the whole catalog.', fg='yellow')


@s3picker.command('link-resource')
@click.option('--catalog', required=True,
              help='Catalog slug from ckanext.s3picker.catalogs')
@click.option('--dataset', required=True, help='Dataset id or name')
@click.option('--name', default=None,
              help='Resource name (defaults to the catalog title)')
def link_resource(catalog, dataset, name):
    """Create or update a dataset resource linking to a catalog's page."""
    conf = _get_catalog(catalog)
    site_user = tk.get_action('get_site_user')({'ignore_auth': True}, {})
    context = {'user': site_user['name'], 'ignore_auth': True}

    try:
        pkg = tk.get_action('package_show')(dict(context), {'id': dataset})
    except tk.ObjectNotFound:
        raise click.BadParameter('Dataset not found: {0}'.format(dataset),
                                 param_hint='--dataset')

    path = picker_path(catalog)
    data = {
        'url': tk.config.get('ckan.site_url', '').rstrip('/') + path,
        'format': RESOURCE_FORMAT,
        'name': name or conf['title'],
        'description': conf['description'] or
        'Browse and download selected files.',
    }
    existing = next(
        (r for r in pkg.get('resources', [])
         if r.get('format') == RESOURCE_FORMAT
         and (r.get('url') or '').endswith(path)),
        None)

    if existing:
        data['id'] = existing['id']
        resource = tk.get_action('resource_patch')(dict(context), data)
        verb = 'Updated'
    else:
        data['package_id'] = pkg['id']
        resource = tk.get_action('resource_create')(dict(context), data)
        verb = 'Created'
    click.secho('{0} resource {1} on dataset {2} -> {3}'.format(
        verb, resource['id'], pkg['name'], data['url']), fg='green')


def get_commands():
    return [s3picker]
