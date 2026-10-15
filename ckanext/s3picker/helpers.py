def s3picker_filesize(num_bytes):
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            break
        size /= 1024
    if unit == 'B':
        return '{0} B'.format(int(size))
    return '{0:.1f} {1}'.format(size, unit)


def s3picker_number(value):
    return '{0:,}'.format(int(value or 0))


def get_helpers():
    return {
        's3picker_filesize': s3picker_filesize,
        's3picker_number': s3picker_number,
    }
