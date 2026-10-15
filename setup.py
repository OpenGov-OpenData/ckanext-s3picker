from setuptools import setup, find_packages

version = '0.1.0'

setup(
    name='ckanext-s3picker',
    version=version,
    description='Browse a pre-indexed S3 prefix and download selected files '
                'via presigned URLs',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    classifiers=[],
    keywords='CKAN S3 download',
    author='OpenGov',
    url='',
    license='AGPL',
    packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
    namespace_packages=['ckanext'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'boto3>=1.26,<2',
    ],
    entry_points='''
        [ckan.plugins]
        s3picker = ckanext.s3picker.plugin:S3PickerPlugin
    ''',
)
