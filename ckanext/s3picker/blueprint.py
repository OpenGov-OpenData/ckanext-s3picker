from flask import Blueprint, jsonify, redirect, request

import ckan.plugins.toolkit as tk

from ckanext.s3picker import aws
from ckanext.s3picker import config as s3config
from ckanext.s3picker import model as s3model

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500

s3picker = Blueprint('s3picker', __name__)


def _json_error(message, status):
    response = jsonify({'error': message})
    response.status_code = status
    return response


def _catalog_access(slug):
    """Returns (catalog, error) where error is 'not_found' or 'forbidden'."""
    try:
        catalog = s3config.get_catalog(slug)
    except tk.ObjectNotFound:
        return None, 'not_found'
    try:
        tk.check_access('s3picker_catalog_access',
                        {'user': tk.g.user}, {'catalog': slug})
    except tk.NotAuthorized:
        return catalog, 'forbidden'
    return catalog, None


def _int_arg(name, default, minimum, maximum):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def picker(catalog):
    conf, error = _catalog_access(catalog)
    if error == 'not_found':
        tk.abort(404, tk._('Catalog not found'))
    if error == 'forbidden':
        if not tk.g.user:
            return tk.redirect_to(tk.url_for('user.login',
                                             came_from=request.path))
        tk.abort(403, tk._('You are not authorized to access this catalog'))

    root = s3model.get_dir(catalog, '')
    return tk.render('s3picker/picker.html', extra_vars={
        'catalog': conf,
        'root': root.as_dict() if root else None,
        'max_files': s3config.max_files_per_request(),
    })


def browse(catalog):
    conf, error = _catalog_access(catalog)
    if error == 'not_found':
        return _json_error('Catalog not found', 404)
    if error == 'forbidden':
        return _json_error('Not authorized', 403)

    path = request.args.get('path', '').strip('/')
    q = request.args.get('q', '').strip()
    page = _int_arg('page', 0, 0, 10 ** 6)
    page_size = _int_arg('page_size', DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)

    if q:
        result = s3model.search(catalog, q, page, page_size)
    else:
        if path and s3model.get_dir(catalog, path) is None:
            return _json_error('Folder not found', 404)
        result = s3model.list_dir(catalog, path, page, page_size)

    result.update({
        'path': path,
        'q': q,
        'page': page,
        'page_size': page_size,
        'has_more': (page + 1) * page_size < result['total'],
    })
    return jsonify(result)


def matches(catalog):
    """Every file matching a search, for "select all matches"."""
    conf, error = _catalog_access(catalog)
    if error == 'not_found':
        return _json_error('Catalog not found', 404)
    if error == 'forbidden':
        return _json_error('Not authorized', 403)

    q = request.args.get('q', '').strip()
    if not q:
        return _json_error('Missing search text.', 400)

    max_files = s3config.max_files_per_request()
    total, total_size, rows = s3model.search_matches(catalog, q, max_files)
    return jsonify({
        'q': q,
        'total': total,
        'total_size': total_size,
        'max_files': max_files,
        'files': [{'id': r.id, 'path': r.relative_path, 'size': r.size_bytes}
                  for r in rows],
    })


def _string_list(value):
    if value is None:
        return []
    if not isinstance(value, list) or not all(
            isinstance(v, str) for v in value):
        raise ValueError
    return value


def download(catalog):
    conf, error = _catalog_access(catalog)
    if error == 'not_found':
        return _json_error('Catalog not found', 404)
    if error == 'forbidden':
        return _json_error('Not authorized', 403)

    data = request.get_json(silent=True) or {}
    try:
        file_ids = _string_list(data.get('files'))
        folders = [f.strip('/') for f in _string_list(data.get('folders'))]
    except ValueError:
        return _json_error('"files" and "folders" must be lists of strings',
                           400)

    limit = s3config.max_files_per_request()
    if len(file_ids) > limit or len(folders) > limit:
        return _json_error(
            'Too many items selected (maximum {0} files).'.format(limit), 400)

    query = s3model.selection_query(catalog, file_ids, folders)
    count = query.count()
    if count == 0:
        return _json_error('No files selected.', 400)
    if count > limit:
        return _json_error(
            'Selection contains {0} files; the maximum per request is {1}. '
            'Select fewer folders and try again.'.format(count, limit), 400)

    files = [{
        'path': row.relative_path,
        'size': row.size_bytes,
        'url': tk.url_for('s3picker.file', catalog=catalog,
                          path=row.relative_path, qualified=True),
    } for row in query]
    return jsonify({
        'count': len(files),
        'total_size': sum(f['size'] for f in files),
        'files': files,
    })


def file(catalog, path):
    """Check access, then redirect to a freshly signed, short-lived S3 URL."""
    conf, error = _catalog_access(catalog)
    if error == 'not_found':
        tk.abort(404, tk._('Catalog not found'))
    if error == 'forbidden':
        # 403 rather than a login redirect, so command-line tools don't
        # save a login page as the file.
        tk.abort(403, tk._('You are not authorized to access this catalog'))

    row = s3model.get_file(catalog, conf['prefix'] + path)
    if row is None:
        tk.abort(404, tk._('File not found'))

    url = aws.generate_presigned_url(aws.get_s3_client(), row.s3_bucket,
                                     row.s3_key, s3config.url_expiry())
    # Keep CKAN from marking the signed redirect as publicly cacheable.
    request.environ['__no_cache__'] = True
    response = redirect(url, code=302)
    response.cache_control.no_store = True
    return response


s3picker.add_url_rule('/custom-downloads/<catalog>', view_func=picker)
s3picker.add_url_rule('/custom-downloads/<catalog>/browse', view_func=browse)
s3picker.add_url_rule('/custom-downloads/<catalog>/matches', view_func=matches)
s3picker.add_url_rule('/custom-downloads/<catalog>/download',
                      view_func=download, methods=['POST'])
s3picker.add_url_rule('/custom-downloads/<catalog>/file/<path:path>',
                      view_func=file)


def get_blueprints():
    return [s3picker]
