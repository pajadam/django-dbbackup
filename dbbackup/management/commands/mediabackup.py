"""
Save media files.
"""
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import os
import tarfile
from fnmatch import fnmatch

from django.core.files.storage import get_storage_class
from django.core.management.base import CommandError

from ... import utils
from ...storage import StorageError, get_storage
from ._base import BaseDbBackupCommand, make_option


class Command(BaseDbBackupCommand):
    help = """Backup media files, gather all in a tarball and encrypt or
    compress."""
    content_type = "media"

    option_list = BaseDbBackupCommand.option_list + (
        make_option("-c", "--clean", help="Clean up old backup files", action="store_true",
                    default=False),
        make_option("-s", "--servername",
                    help="Specify server name to include in backup filename"),
        make_option("-z", "--compress", help="Compress the archive", action="store_true",
                    default=False),
        make_option("-e", "--encrypt", help="Encrypt the backup files", action="store_true",
                    default=False),
        make_option("-E", "--exclude", default=[], action="append",
                    help="Specify files to exclude from media backup. "
                         "You can use Unix shell-style wildcards, "
                         "e.g. 'path_to_exclude/*' or '*.jpg'"),
        make_option("-o", "--output-filename", default=None,
                    help="Specify filename on storage"),
        make_option("-O", "--output-path", default=None,
                    help="Specify where to store on local filesystem",)
    )

    @utils.email_uncaught_exception
    def handle(self, **options):
        self.verbosity = options.get('verbosity')
        self.quiet = options.get('quiet')
        self._set_logger_level()

        self.encrypt = options.get('encrypt', False)
        self.compress = options.get('compress', False)
        self.servername = options.get('servername')

        self.exclude_patterns = options.get('exclude')

        self.filename = options.get('output_filename')
        self.path = options.get('output_path')
        try:
            self.media_storage = get_storage_class()()
            self.storage = get_storage()
            self.backup_mediafiles()
            if options.get('clean'):
                self._cleanup_old_backups(servername=self.servername)

        except StorageError as err:
            raise CommandError(err)

    def _explore_storage(self):
        """Generator of all files contained in media storage."""
        path = ''
        dirs = [path]
        while dirs:
            path = dirs.pop()
            subdirs, files = self.media_storage.listdir(path)
            for media_filename in files:
                yield os.path.join(path, media_filename)
            dirs.extend([os.path.join(path, subdir) for subdir in subdirs])

    def _is_excluded(self, media_filename):
        """Check if given media file should be excluded from backup"""
        for pattern in self.exclude_patterns:
            if fnmatch(media_filename, pattern):
                return True
        return False

    def _create_tar(self, name):
        """Create TAR file."""
        fileobj = utils.create_spooled_temporary_file()
        mode = 'w:gz' if self.compress else 'w'
        tar_file = tarfile.open(name=name, fileobj=fileobj, mode=mode)
        for media_filename in self._explore_storage():
            # Exclude files from mediabackup according to exclude_patterns
            if self.exclude_patterns and self._is_excluded(media_filename):
                continue
            tarinfo = tarfile.TarInfo(media_filename)
            media_file = self.media_storage.open(media_filename)
            tarinfo.size = len(media_file)
            tar_file.addfile(tarinfo, media_file)
        # Close the TAR for writing
        tar_file.close()
        return fileobj

    def backup_mediafiles(self):
        """
        Create backup file and write it to storage.
        """
        # Create file name
        extension = "tar%s" % ('.gz' if self.compress else '')
        filename = utils.filename_generate(extension,
                                           servername=self.servername,
                                           content_type=self.content_type)
        tarball = self._create_tar(filename)
        # Apply trans
        if self.encrypt:
            encrypted_file = utils.encrypt_file(tarball, filename)
            tarball, filename = encrypted_file

        self.logger.debug("Backup size: %s", utils.handle_size(tarball))
        # Store backup
        tarball.seek(0)
        if self.path is None:
            self.write_to_storage(tarball, filename)
        else:
            self.write_local_file(tarball, self.path)
