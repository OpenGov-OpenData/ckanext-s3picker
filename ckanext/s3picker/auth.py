import ckan.plugins.toolkit as tk

from ckanext.s3picker import config as s3config


@tk.auth_allow_anonymous_access
def s3picker_catalog_access(context, data_dict):
    try:
        catalog = s3config.get_catalog(data_dict.get('catalog'))
    except tk.ObjectNotFound:
        return {'success': False, 'msg': tk._('Unknown catalog')}
    if not catalog['private'] or context.get('auth_user_obj'):
        return {'success': True}
    return {
        'success': False,
        'msg': tk._('You must be logged in to access this catalog'),
    }


def get_auth_functions():
    return {'s3picker_catalog_access': s3picker_catalog_access}
