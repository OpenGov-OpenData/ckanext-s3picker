import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from ckanext.s3picker import auth, blueprint, cli, helpers
from ckanext.s3picker import config as s3config
from ckanext.s3picker import model as s3model


class S3PickerPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IConfigurable)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.IClick)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.ITemplateHelpers)

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_resource('assets', 'ckanext-s3picker')

    # IConfigurable

    def configure(self, config_):
        s3config.check_required_config(config_)
        # Runs after model.init_model(), so the engine is bound here.
        s3model.setup()

    # IBlueprint

    def get_blueprint(self):
        return blueprint.get_blueprints()

    # IClick

    def get_commands(self):
        return cli.get_commands()

    # IAuthFunctions

    def get_auth_functions(self):
        return auth.get_auth_functions()

    # ITemplateHelpers

    def get_helpers(self):
        return helpers.get_helpers()
