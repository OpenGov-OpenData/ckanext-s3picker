# ckanext-s3picker

A file-picker page for large, static collections of files in S3 (e.g. LiDAR
tiles). Users browse a folder tree, select files and/or whole folders, and get
CKAN download links. Like ckanext-cloudstorage, each link checks access and
then redirects to a freshly signed, short-lived S3 URL, so the file is
downloaded directly from S3 — CKAN never proxies the file contents.

- Each collection is a **catalog**: a named S3 bucket + prefix defined in
  `ckan.ini`.
- Each catalog has a page at `/custom-downloads/<catalog>`. Pages are not tied
  to a CKAN dataset, so a dataset can be deleted/recreated and simply re-linked.
- The file listing comes from a database index built once per catalog with
  `ckan s3picker build-index` (the page never lists S3 live).
- S3 credentials come from `ckanext.s3picker.driver_options`, or, if that is
  not set, are reused from
  [ckanext-cloudstorage](https://github.com/OpenGov-OpenData/ckanext-cloudstorage).

## Requirements

- CKAN 2.9 (tested), written to run unmodified on CKAN 2.10 / 2.11.
- Python 3.8+.
- Either `ckanext.s3picker.driver_options` (see below), or
  `ckanext-cloudstorage` installed, enabled and configured so its
  `ckanext.cloudstorage.driver_options` can be reused. cloudstorage is not
  listed in `install_requires`; install it separately if you rely on it.

## Installation

```bash
pip install -e /path/to/ckanext-cloudstorage
pip install -e /path/to/ckanext-s3picker
```

Add `s3picker` to `ckan.plugins` (after `cloudstorage`, if you use it):

```ini
ckan.plugins = ... cloudstorage s3picker
```

The plugin creates its tables (`s3picker_file`, `s3picker_dir`) on startup if
they do not exist; no `db upgrade` step is needed.

## Configuration

```ini
# Required. JSON (or a Python dict literal) mapping catalog slug -> settings.
ckanext.s3picker.catalogs = {
    "county-a-2024": {"prefix": "county-a/2024/", "title": "County A 2024 LiDAR"},
    "county-b-2023": {"bucket": "other-bucket", "prefix": "county-b/2023/", "private": true}
  }

# Bucket used by catalogs that don't set "bucket".
ckanext.s3picker.default_bucket = my-lidar-bucket

# Optional (defaults shown). The expiry (seconds) applies to the S3 URL each
# download link redirects to; it is signed when the link is opened, and a
# download that has started keeps going after it expires.
ckanext.s3picker.presigned_url_expiry = 60
ckanext.s3picker.max_files_per_request = 1000

# Optional. S3 credentials for the catalog buckets. If unset, the credentials
# in ckanext.cloudstorage.driver_options are reused.
ckanext.s3picker.driver_options = {"key": "AKIA...", "secret": "...", "region_name": "us-west-2"}
```

`ckanext.s3picker.driver_options` uses the same format as cloudstorage's:

| Key | Description |
| --- | --- |
| `key`, `secret` | Access key pair. Omit both to use boto3's default credential chain (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars, `AWS_PROFILE`, or the server's instance role). |
| `region_name` (or `region`) | Bucket region. Needed for correct presigned URLs outside `us-east-1`. |
| `host` | Only for non-AWS S3-compatible services (e.g. MinIO). AWS hosts are ignored. |

Setting it decouples s3picker from cloudstorage, e.g. a staging portal can keep
uploading resources to a staging bucket while s3picker reads a production
LiDAR bucket with separate, read-only credentials. s3picker never writes to S3.

Catalog settings:

| Key | Required | Description |
| --- | --- | --- |
| `prefix` | yes | Key prefix within the bucket (`""` for the whole bucket). A trailing `/` is added if missing. |
| `bucket` | no | Falls back to `ckanext.s3picker.default_bucket`. |
| `title` | no | Page heading and default resource name. Defaults to the slug. |
| `description` | no | Shown on the page and used as the resource description. |
| `private` | no | `true` requires users to be logged in (any CKAN user). Default `false` (public). |

The credentials s3picker uses need only `s3:ListBucket` (for `build-index`)
and `s3:GetObject` (for presigned URLs) on each catalog's bucket/prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "s3:ListBucket",
     "Resource": "arn:aws:s3:::my-lidar-bucket",
     "Condition": {"StringLike": {"s3:prefix": ["county-a/2024/*"]}}},
    {"Effect": "Allow", "Action": "s3:GetObject",
     "Resource": "arn:aws:s3:::my-lidar-bucket/county-a/2024/*"}
  ]
}
```

## Usage

Build (or rebuild) a catalog's index. Safe to re-run; it replaces the
catalog's index in a single transaction:

```bash
ckan -c /etc/ckan/default/ckan.ini s3picker build-index --catalog county-a-2024
```

For a quick test against a large bucket, `--limit N` indexes only the first N
files (in S3 key order). Run again without `--limit` for the full index.

Add a resource to a dataset that links to the catalog's page (format
`Custom Download`). Re-running updates the existing resource instead of
adding a duplicate, so it can also be used to re-link a recreated dataset:

```bash
ckan -c /etc/ckan/default/ckan.ini s3picker link-resource \
    --catalog county-a-2024 --dataset my-dataset [--name "Download LiDAR tiles"]
```

On the page, users can expand folders (loaded lazily, 100 entries at a time),
search by file name/path, select files or whole folders, and click
**Get download links**. Results can be opened one by one or saved as
a URL list for `wget -i urls.txt`.

When a search has results, **Select all N matches** selects every matching file
(not just the ones on screen) in one click. The matches are added as ordinary
selected files, so you can uncheck a few afterwards or use **Clear selection**,
and files already covered by a selected folder aren't counted twice. If there
are more matches than `ckanext.s3picker.max_files_per_request`, the button is
disabled and you're asked to narrow the search.

The links are CKAN URLs (`/custom-downloads/<catalog>/file/<path>`), never
signed S3 URLs, so they can be shared without handing out S3 access: every
request re-checks the catalog's access rules and only files in the index can
be fetched. For private catalogs, command-line tools need a CKAN API token:

```bash
wget --content-disposition --header "Authorization: <API token>" -i urls.txt
```

After the redirect the browser does see the short-lived S3 URL (e.g. in its
download manager); hiding it entirely would require streaming files through
CKAN. Keep `presigned_url_expiry` short so that URL is of little use.

### Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/custom-downloads/<catalog>` | Picker page |
| GET | `/custom-downloads/<catalog>/browse?path=&page=&page_size=&q=` | JSON folder listing, or file search when `q` is set |
| GET | `/custom-downloads/<catalog>/matches?q=` | JSON list of every file matching `q` (empty `files` if there are more than the per-request limit); used by "Select all matches" |
| POST | `/custom-downloads/<catalog>/download` | JSON body `{"files": [ids], "folders": [paths]}`; returns CKAN download links |
| GET | `/custom-downloads/<catalog>/file/<path>` | Checks access, then redirects (302) to a presigned S3 URL |

Private catalogs redirect anonymous users to the login page from the picker
page, and return 403 from the other endpoints.

## Development

Tests use `pytest-ckan` and [moto](https://github.com/getmoto/moto) to mock
S3. They need a CKAN test environment (Postgres, Solr, Redis) and
`ckanext-cloudstorage` installed:

```bash
pip install -r requirements.txt -r dev-requirements.txt
pip install -e . -e ../ckanext-cloudstorage
ckan -c test.ini db init
pytest --ckan-ini=test.ini ckanext/s3picker/tests
```

CI (`.github/workflows/test.yml`) runs the suite against CKAN 2.9 and 2.11.
