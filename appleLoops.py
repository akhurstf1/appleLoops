#!/usr/bin/python

"""
Downloads required audio loops for GarageBand, Logic Pro X, and MainStage 3.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

     https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Elements of FoundationPlist.py are used in this tool.
https://github.com/munki/munki
"""

import argparse
import collections
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import urllib2
from glob import glob
from random import uniform
from time import sleep
from time import strftime
from urlparse import urlparse

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSData  # NOQA
from Foundation import NSPropertyListSerialization
from Foundation import NSPropertyListMutableContainers
from Foundation import NSPropertyListXMLFormat_v1_0  # NOQA
# pylint: enable=E0611

# Script information
__author__ = 'Carl Windus'
__copyright__ = 'Copyright 2016, Carl Windus'
__credits__ = ['Greg Neagle', 'Matt Wilkie']
__version__ = '1.1.4'
__date__ = '2017-06-04'

__license__ = 'Apache License, Version 2.0'
__maintainer__ = 'Carl Windus: https://github.com/carlashley/appleLoops'
__status__ = 'Production'


# Acknowledgements to Greg Neagle and `munki` for this section of code.
class FoundationPlistException(Exception):
    """Basic exception for plist errors"""
    pass


class NSPropertyListSerializationException(FoundationPlistException):
    """Read/parse error for plists"""
    pass


def readPlistFromString(data):
    """Read a plist data from a string. Return the root object."""
    try:
        plistData = buffer(data)
    except TypeError, err:
        raise NSPropertyListSerializationException(err)
    dataObject, dummy_plistFormat, error = (
        NSPropertyListSerialization.
        propertyListFromData_mutabilityOption_format_errorDescription_(
            plistData, NSPropertyListMutableContainers, None, None))
    if dataObject is None:
        if error:
            error = error.encode('ascii', 'ignore')
        else:
            error = "Unknown error"
        raise NSPropertyListSerializationException(error)
    else:
        return dataObject


class AppleLoops():
    """Class contains functions for parsing Apple's plist feeds for GarageBand
    and Logic Pro, as well as downloading loops content."""
    def __init__(self, download_location=None, dry_run=True,
                 package_set=None, package_year=None,
                 mandatory_pkg=False, optional_pkg=False,
                 caching_server=None, files_process=None,
                 jss_mode=False, dmg_path=None,
                 munki_loops_path=None):
        try:
            if not download_location:
                self.download_location = os.path.join('/tmp', 'appleLoops')
            else:
                self.download_location = download_location

            # Default to dry run
            self.dry_run = dry_run

            # Set package set to download
            self.package_set = package_set

            # Set package year to download
            self.package_year = package_year

            # Set mandatory package to option specified. Default is false.
            self.mandatory_pkg = mandatory_pkg

            # Set optional package to option specified. Default is false.
            self.optional_pkg = optional_pkg

            # Base URL for loops
            # This URL needs to be re-assembled into the correct format of:
            # http://audiocontentdownload.apple.com/lp10_ms3_content_YYYY/filename.ext
            self.base_url = (
                'http://audiocontentdownload.apple.com/lp10_ms3_content_'
            )

            # Configure cache server if argument is provided
            if caching_server:
                self.caching_server = caching_server.rstrip('/')

                # Base URL needs to change
                self.source_url = '?source=%s' % urlparse(self.base_url).netloc
                self.cache_base_url = (
                    '%s/lp10_ms3_content_' % self.caching_server
                )
            else:
                self.caching_server = None

            # Processing specific files or not
            if files_process:
                self.files_process = files_process
            else:
                self.files_process = False

            # Switch JSS mode on or off (modifies output in the console to not
            # include the percentage completed)
            if jss_mode:
                self.jss_mode = True
            else:
                self.jss_mode = False

            if dmg_path:
                self.dmg_path = dmg_path
            else:
                self.dmg_path = False

            # User-Agent string for this tool
            self.user_agent = 'appleLoops/%s' % __version__

            # Dictionary of plist feeds to parse - these are Apple provided
            # plists.
            # Will look into possibly using local copies maintained in
            # GarageBand/Logic Pro X app bundles.
            # Note - dropped support for anything prior to 2016 releases
            self.feeds = self.request_url('https://raw.githubusercontent.com/carlashley/appleLoops/master/com.github.carlashley.appleLoops.feeds.plist')  # NOQA
            self.config = readPlistFromString(self.feeds.read())
            self.loop_feed_locations = self.config['loop_feeds']
            self.alt_loop_feed_base_url = 'https://raw.githubusercontent.com/carlashley/appleLoops/master/lp10_ms3_content_'  # NOQA
            self.loop_years = self.config['loop_years']

            self.file_choices = []
            # Seriously inelegant, but it works :shrug:
            for year in self.config['loop_years']:
                for app_feed in self.config['loop_feeds']:
                    for plist in self.loop_feed_locations[app_feed][year]:
                        # This builds the choices list for the argparse further
                        # down
                        if plist not in self.file_choices:
                            self.file_choices.append(str(plist))

            self.feeds.close()

            # Create a named tuple for our loops master list
            # These 'attributes' are:
            # pkg_name = Package file name
            # pkg_url = Package URL from Apple servers
            # pkg_mandatory = Required package for whatever app requires it
            # pkg_size = Package size based on it's 'Content-Length' - in bytes
            # pkg_year = The package release year (i.e. 2016, or 2013, etc)
            # pkg_loop_for = logicpro or garageband
            self.Loop = collections.namedtuple('Loop', ['pkg_name',
                                                        'pkg_url',
                                                        'pkg_mandatory',
                                                        'pkg_size',
                                                        'pkg_year',
                                                        'pkg_loop_for',
                                                        'pkg_plist'])

            # Empty list to put all the content that we're going to work on
            # into.
            self.master_list = []
            self.file_copy_master_list = []

            # Download amount list
            self.download_amount = []
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    def exit_out(self):
        sys.exit()

    def build_url(self, loop_year, filename):
        """Builds the URL for each plist feed"""
        try:
            seperator = '/'

            # If caching server and filename ends with '.pkg', we use a special
            # URL format, so use self.cache_base_url instead of self.base_url
            if self.caching_server and filename.endswith('.pkg'):
                built_url = seperator.join([self.cache_base_url + loop_year,
                                            filename + self.source_url])
            else:
                built_url = seperator.join([self.base_url + loop_year,
                                            filename])

            return built_url
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    # Wrap around urllib2 for requesting URL's because this is done often
    # enough
    def request_url(self, url):
        try:
            req = urllib2.Request(url)
            req.add_unredirected_header('User-Agent', self.user_agent)
            req = urllib2.urlopen(req)
            return req
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    def add_loop(self, package_name, package_url,
                 package_mandatory, package_size,
                 package_year, loop_for, plist):
        """Add's the loop to the master list. A named tuple is used to make
        referencing attributes of each loop easier."""
        try:
            # Apple aren't consistent with file sizes - so if the file size
            # comes from the plist, we may need to remove characters!
            try:
                package_size = package_size.replace('.', '')
            except:
                pass

            # Use the tuple Luke!
            loop = self.Loop(
                pkg_name=package_name,
                pkg_url=package_url,
                pkg_mandatory=package_mandatory,
                pkg_size=package_size,
                pkg_year=package_year,
                pkg_loop_for=loop_for,
                pkg_plist=plist
            )

            if loop not in self.master_list:
                self.master_list.append(loop)
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    def process_plist(self, loop_year, plist):
        """Processes the Apple plist feed. Makes use of readPlistFromString()
        as python's native plistlib module doesn't read binary plists, which
        Apple has used in past releases."""
        try:
            if self.jss_mode:
                _jss_mode = 'on'
            else:
                _jss_mode = 'off'

            print 'Processing items from %s and saving to %s. JSS mode %s' % (
                            plist, self.download_location, _jss_mode
                        )
            # Note - the package size specified in the plist feeds doesn't
            # always match the actual package size, so check header
            # 'Content-Length' to determine correct package size.
            plist_url = self.build_url(loop_year, plist)
            alt_plist_url = '%s%s/%s' % (self.alt_loop_feed_base_url,
                                         loop_year,
                                         plist)

            # Split extension from the plist for folder creation
            _plist = os.path.splitext(plist)[0]

            # URL requests
            try:
                request = self.request_url(plist_url)
            except:
                print 'Failing over to %s' % alt_plist_url
                request = self.request_url(alt_plist_url)

            # Process request data into dictionary
            data = readPlistFromString(request.read())
            loop_for = os.path.splitext(plist)[0]

            # I don't like using regex, so here's a lambda to remove numbers
            # part of the loop URL to use as an indicator for what app
            # the loop is for
            loop_for = ''.join(map(lambda c: '' if c in '0123456789' else c,
                                   loop_for))

            for pkg in data['Packages']:
                name = data['Packages'][pkg]['DownloadName']
                url = self.build_url(loop_year, name)

                # The 'IsMandatory' may not exist, if it doesn't, then the
                # package isn't mandatory, duh.
                try:
                    mandatory = data['Packages'][pkg]['IsMandatory']
                except:
                    mandatory = False

                # If the package download name starts with ../ then we need to
                # fix the URL up to point to the right path, and adjust the
                # package name. Additionally, replace the year with the correct
                # year
                if name.startswith('../'):
                    url = 'http://audiocontentdownload.apple.com/%s' % name[3:]
                    name = os.path.basename(name)

                # List comprehension to get the year
                year = [x[-4:] for x in url.split('/') if 'lp10_ms3' in x][0]

                # This step adds time to the processing of the plist
                try:
                    request = self.request_url(url)
                    size = request.info().getheader('Content-Length').strip()

                    # Close out the urllib2 request
                    request.close()
                except:
                    size = data['Packages'][pkg]['DownloadSize']

                # Add to the loops master list
                if self.mandatory_pkg and not self.optional_pkg:
                    if mandatory:
                        self.add_loop(name, url, mandatory, size, year,
                                      loop_for, _plist)
                elif self.optional_pkg and not self.mandatory_pkg:
                    if not mandatory:
                        self.add_loop(name, url, mandatory, size, year,
                                      loop_for, _plist)
                else:
                    pass

                if not self.mandatory_pkg and not self.optional_pkg:
                    self.add_loop(name, url, mandatory, size, year, loop_for,
                                  _plist)

            # Tidy up the urllib2 request
            request.close()
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    def build_master_list(self):
        """This builds the master list of audio content so it (the master list)
        can be processed in other functions. Yeah, there's some funky Big O
        here."""

        # This is where we'll check if we're processing a specific file or not
        try:
            # Yo dawg, heard you like for loops, so I put for loops in your for
            # loops in your for loops
            if self.files_process:
                # This loops through package sets, and checks if we're only
                # processing from a specific file, if so, just do the tango for
                # that file.
                for pkg_set in self.package_set:
                    for year in self.package_year:
                        package_plist = self.loop_feed_locations[pkg_set][year]
                        for plist in self.files_process:
                            if plist in package_plist:
                                self.process_plist(year, plist)
            else:
                # Here we just loop through all the package sets and do the
                # tango for everything that is defaulted to.
                for pkg_set in self.package_set:
                    for year in self.package_year:
                        package_plist = self.loop_feed_locations[pkg_set][year]
                        for plist in package_plist:
                            self.process_plist(year, plist)
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    def convert_size(self, file_size, precision=2):
        """Converts the package file size into a human readable number."""
        try:
            try:
                suffixes = ['B', 'KB', 'MB', 'GB', 'TB']
                suffix_index = 0
                while file_size > 1024 and suffix_index < 4:
                    suffix_index += 1
                    file_size = file_size/1024.0

                return '%.*f%s' % (precision, file_size,
                                   suffixes[suffix_index])
            except Exception as e:
                raise e
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    def progress_output(self, loop, percent, human_fs, items_counter):
        """Basic progress count that self updates while a
        file is downloading."""
        try:
            try:
                stats = 'Downloading %s: %s' % (items_counter, loop.pkg_name)
                progress = '[%0.2f%% of %s]' % (percent, human_fs)
                sys.stdout.write("\r%s %s" % (stats, progress))
                sys.stdout.flush()
            except Exception as e:
                raise e
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    def make_storage_location(self, folder):
        """Makes the storage location for the audio content if it doesn't exist.
        Tries to expand paths and variables."""
        try:
            try:
                folder = os.path.expanduser(folder)
            except:
                pass

            try:
                folder = os.path.expandvar(folder)
            except:
                pass

            if not os.path.isdir(folder):
                try:
                    os.makedirs(folder)
                except Exception as e:
                    raise e
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    # Test if the file being downloaded exists
    def file_exists(self, loop, local_file):
        """Tests if the remote file already exists locally and it is the
        correct file size. There is potential for some file size discrepancy
        based on how many blocks the file actually takes up on local storage.
        So some files may end up being re-downloaded as a result.
        To get around this, calculate the number of blocks the local file
        consumes, and compare that to the number of blocks the remote file
        would consume."""
        try:
            if os.path.exists(local_file):
                # Get the block size of the file on disk
                block_size = os.stat(local_file).st_blksize

                # Remote file size
                remote_blocks = int(int(loop.pkg_size)/block_size)

                # Local file size
                local_blocks = int(os.path.getsize(local_file)/block_size)

                # Compare if local number of blocks consumed is equal to or
                # greater than the number of blocks the remote file will
                # consume.
                if local_blocks >= remote_blocks:
                    return True
                else:
                    return False
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    # Test duplicate file
    def duplicate_file(self, loop):
        """Simple test to see if a duplicate file exists elsewhere in the loops
        download path."""
        try:
            glob_path = glob('%s/*/*/*/' % self.download_location)

            # Test if file exists
            for path in glob_path:
                if self.file_exists(loop, os.path.join(path, loop.pkg_name)):
                    return True
                else:
                    return False
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    # Copy duplicate file, don't download
    def copy_duplicate(self, loop, counter):
        """Used to copy a duplicate file so downloads are not wasted. Don't
        wrap this in a keyboard/system exit try statement as it could cause
        file writes to go bad."""
        glob_path = glob('%s/*/*/*/' % self.download_location)
        local_directory = self.local_directory(loop)
        local_file = os.path.join(local_directory, loop.pkg_name)

        # Test if file exists, then test if the file exists and matches the
        # size it should be, if so, we can copy it.
        if not self.file_exists(loop, local_file):
            for path in glob_path:
                if self.file_exists(loop, os.path.join(path, loop.pkg_name)):
                    existing_copy = os.path.join(path, loop.pkg_name)
                    if not self.dry_run:
                        # Make directories otherwise the copy operation fails
                        self.make_storage_location(local_directory)
                        shutil.copy2(existing_copy, local_file)
                        print 'Copied %s of %s: %s' % (
                            counter, len(self.master_list), existing_copy
                        )
                        break
                    else:
                        print 'Copy: %s' % existing_copy
                        break
        else:
            if not self.dry_run:
                    print 'Skipped %s of %s: %s - file exists' % (
                        counter, len(self.master_list), loop.pkg_name
                    )
            else:
                print 'Skip: %s - file exists' % loop.pkg_name

    # Test if loop is mandatory or not, and return the correct local directory
    def local_directory(self, loop):
        """Just a quick test to see if the loop is optional or mandatory, and
        return the correct path for either type."""
        directory_path = (
            os.path.join(
                self.download_location,
                loop.pkg_plist  # Trying a different approach to loops
                # loop.pkg_loop_for,
                # loop.pkg_year,
            )
        )
        if loop.pkg_mandatory:
            return os.path.join(directory_path, 'mandatory')
        else:
            return os.path.join(directory_path, 'optional')

    # Downloads the loop file
    def download(self, loop, counter):
        """Downloads the loop, if the dry run option has been set, then it will
        only output what it would download, along with the file size."""
        try:
            local_directory = self.local_directory(loop)
            local_file = os.path.join(local_directory, loop.pkg_name)

            # Do the download if this isn't a dry run
            if not self.dry_run:
                # Only create the output directory if this isn't a dry run
                # Make the download directory
                self.make_storage_location(local_directory)

                # If the file doesn't already exist, or isn't a complete file,
                # download it
                if not self.file_exists(loop, local_file):
                    try:
                        request = self.request_url(loop.pkg_url)
                    except Exception as e:
                        raise e
                    else:
                        # Open a local file to write into in binary format
                        local_file = open(local_file, 'wb')
                        bytes_so_far = 0

                        # This bit does the download
                        while True:
                            buffer = request.read(8192)
                            if not buffer:
                                if not self.jss_mode:
                                    print('')
                                break

                            # Re-calculate downloaded bytes
                            bytes_so_far += len(buffer)

                            # Write out download file to the loop_file opened
                            local_file.write(buffer)
                            # local_file.flush()
                            os.fsync(local_file)

                            # Calculate percentage
                            percent = (
                                float(bytes_so_far) / float(loop.pkg_size)
                            )
                            percent = round(percent*100.0, 2)

                            # Some files take up more space locally than
                            # remote, so if percentage exceeds 100%, cap it.
                            if percent >= 100.0:
                                percent = 100.0

                            # Output progress made
                            items_count = '%s of %s' % (counter,
                                                        len(self.master_list))
                            if not self.jss_mode:
                                self.progress_output(loop, percent,
                                                     self.convert_size(float(
                                                         loop.pkg_size)),
                                                     items_count)
                    finally:
                        try:
                            request.close()
                            self.download_amount.append(float(loop.pkg_size))
                        except:
                            pass
                        else:
                            # Let a random sleep of 1-2 seconds happen between
                            # each download
                            pause = uniform(1, 2)
                            sleep(pause)
                else:
                    print 'Skipped %s of %s: %s - file exists' % (
                        counter, len(self.master_list), loop.pkg_name
                    )
            else:
                if not self.file_exists(loop, local_file):
                    print 'Download: %s - %s' % (
                        loop.pkg_name, self.convert_size(float(loop.pkg_size))
                    )
                    self.download_amount.append(float(loop.pkg_size))
                else:
                    print 'Skip: %s - file exists' % loop.pkg_name
        except (KeyboardInterrupt, SystemExit):
            self.exit_out()

    # This function builds a DMG using hdutil
    def build_dmg(self, dmg_path=None):
        '''Builds a DMG of the downloaded loops. If no source and dmg path
        provided, source defaults to default download location when class is
        initialised and dmg path to /tmp/appleLoops_YYYY-MM-DD.dmg.
        Fallback unlikely to happen as the argument _must_ have a path
        supplied as defined in the argparse in __main__.'''
        source_path = self.download_location

        # If no dmg path is provided, we need a sane default location and
        # filename.
        if not dmg_path:
            dmg_path = os.path.join('/tmp', 'appleLoops_%s.dmg' % strftime('%Y-%m-%d'))  # NOQA
        else:
            # Expand user or variables that might be used in the path
            try:
                dmg_path = os.path.expanduser(dmg_path)
            except:
                pass

            try:
                dmg_path = os.path.expandvar(dmg_path)
            except:
                pass

        cmd = ['/usr/bin/hdiutil', 'create', '-volname', 'appleLoops', '-srcfolder', source_path, dmg_path]  # NOQA

        try:
            if self.dry_run:
                print 'Build %s from %s' % (dmg_path, source_path)
            else:
                print 'Building %s from %s' % (dmg_path, source_path)
                subprocess.check_call(cmd)
        except:
            raise

    # Build digest for a specific file
    def file_digest(self, file_path, digest_type=None):
        '''Creates a digest based on the digest_type argument.
        digest_type defaults to SHA256.'''
        valid_digests = ['md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512']
        block_size = 65536

        if not digest_type:
            digest_type = 'sha256'

        if digest_type in valid_digests:
            h = hashlib.new(digest_type)
            with open(file_path, 'rb') as f:
                for block in iter(lambda: f.read(block_size), b''):
                    h.update(block)
                return h.hexdigest()
        else:
            raise Exception('%s not a valid digest - choose from %s' %
                            (digest_type, valid_digests))

    # Compare two digests
    def compare_digests(self, digest_a, digest_b):
        if digest_a == digest_b:
            return True
        else:
            return False

    # This is the primary processor for the main function - only used for
    # command line based script usage
    def main_processor(self):
        try:
            """This is the main processor function, it should only be called in the
            main() function - i.e. only for use by the command line."""
            # Build master list
            self.build_master_list()

            # Do the download, and supply counter for feedback on progress
            counter = 1
            download_counter = 0
            for loop in self.master_list:
                if self.duplicate_file(loop):
                    self.copy_duplicate(loop, counter)
                else:
                    if self.jss_mode:
                        print 'Downloading %s of %s: %s - %s' % (
                            counter, len(self.master_list), loop.pkg_name,
                            self.convert_size(float(loop.pkg_size))
                        )
                    self.download(loop, counter)
                    download_counter += 1
                counter += 1

            # Additional information for end of download run
            download_amount = sum(self.download_amount)

            if self.dry_run:
                print '%s packages to process, %s (%s) to download' % (
                    len(self.master_list), download_counter,
                    self.convert_size(download_amount)
                )
            else:
                if len(self.download_amount) >= 1:
                    print 'Downloaded %s packages (%s) ' % (
                        download_counter, self.convert_size(download_amount)
                    )

            if self.dmg_path:
                self.build_dmg(dmg_path=self.dmg_path)

        except (KeyboardInterrupt, SystemExit):
            print ''
            sys.exit(0)


def main():
    # Handle keyboard signal interrupt
    def signal_handler(signal, frame):
        print 'Exiting'
        sys.exit()

    signal.signal(signal.SIGINT, signal_handler)

    class SaneUsageFormat(argparse.HelpFormatter):
        """
        Makes the help output somewhat more sane.
        Code used was from Matt Wilkie.
        http://stackoverflow.com/questions/9642692/argparse-help-without-duplicate-allcaps/9643162#9643162
        """

        def _format_action_invocation(self, action):
            if not action.option_strings:
                default = self._get_default_metavar_for_positional(action)
                metavar, = self._metavar_formatter(action, default)(1)
                return metavar

            else:
                parts = []

                # if the Optional doesn't take a value, format is:
                #    -s, --long
                if action.nargs == 0:
                    parts.extend(action.option_strings)

                # if the Optional takes a value, format is:
                #    -s ARGS, --long ARGS
                else:
                    default = self._get_default_metavar_for_optional(action)
                    args_string = self._format_args(action, default)
                    for option_string in action.option_strings:
                        parts.append(option_string)

                    return '%s %s' % (', '.join(parts), args_string)

                return ', '.join(parts)

        def _get_default_metavar_for_optional(self, action):
            return action.dest.upper()

    parser = argparse.ArgumentParser(formatter_class=SaneUsageFormat)
    exclusive_group = parser.add_mutually_exclusive_group()

    # Option to build DMG
    parser.add_argument(
        '--build-dmg',
        type=str,
        nargs=1,
        dest='build_dmg',
        metavar='/path/to/file.dmg',
        help='Builds a DMG of the downloaded loops.',
        required=False
    )

    # Option for cache server URL
    parser.add_argument(
        '-c', '--cache-server',
        type=str,
        nargs=1,
        dest='cache_server',
        metavar='http://url:port',
        help='Use cache server to download content through',
        required=False
    )

    # Option for output directory
    parser.add_argument(
        '-d', '--destination',
        type=str,
        nargs=1,
        dest='destination',
        metavar='<folder>',
        help='Download location for loops content',
        required=False
    )

    # Option for parsing a particular file
    parser.add_argument(
        '-f', '--file',
        type=str,
        nargs='+',
        dest='plist_file',
        choices=(AppleLoops().file_choices),
        # choices=['foo'],
        # metavar='<file>',
        help='Specify one or more files to process loops from',
        required=False
    )

    # Option for JSS special mode
    parser.add_argument(
        '-j', '--jss',
        action='store_true',
        dest='jss_quiet_output',
        help='Minimal output to reduce spamming the JSS console',
        required=False
    )

    # Option for mandatory content only
    exclusive_group.add_argument(
        '-m', '--mandatory-only',
        action='store_true',
        dest='mandatory',
        help='Download mandatory content only',
        required=False
    )

    # Option for dry run
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        dest='dry_run',
        help='Dry run to indicate what will be downloaded',
        required=False
    )

    # Option for optional content only
    exclusive_group.add_argument(
        '-o', '--optional-only',
        action='store_true',
        dest='optional',
        help='Download optional content only',
        required=False
    )

    # Option for package set (either 'garageband' or 'logicpro')
    parser.add_argument(
        '-p', '--package-set',
        type=str,
        nargs='+',
        dest='package_set',
        choices=['garageband', 'logicpro', 'mainstage'],
        help='Specify one or more package set to download',
        required=False
    )

    # Option for content year
    parser.add_argument(
        '-y', '--content-year',
        type=str,
        nargs='+',
        dest='content_year',
        choices=AppleLoops().loop_years,
        help='Specify one or more content year to download',
        required=False
    )

    args = parser.parse_args()

    # Set which package set to download
    if args.package_set:
        pkg_set = args.package_set
    else:
        if args.plist_file:
            pkg_set = ['garageband', 'logicpro', 'mainstage']
        else:
            pkg_set = ['garageband']

    # Set output directory
    if args.destination and len(args.destination) is 1:
        store_in = args.destination[0]
    else:
        store_in = None

    # Set content year
    if not args.content_year:
        year = ['2016']
    else:
        year = args.content_year

    # Set output directory
    if args.cache_server and len(args.cache_server) is 1:
        cache_server = args.cache_server[0]
    else:
        cache_server = None

    # File process
    if args.plist_file:
        files_to_process = args.plist_file
        # Sort these files so we can take advantage of duplicate files
        files_to_process.sort()
    else:
        files_to_process = None

    # Suppressed mode for JSS output
    if args.jss_quiet_output:
        jss_output_mode = True
    else:
        jss_output_mode = False

    # DMG Path
    if args.build_dmg and len(args.build_dmg) is 1:
        if args.build_dmg[0].endswith('.dmg'):
            build_dmg = args.build_dmg[0]
        else:
            print ('%s must end with .dmg' % args.build_dmg[0])
            sys.exit(1)
    else:
        build_dmg = None

    # Instantiate the class AppleLoops with options
    loops = AppleLoops(download_location=store_in,
                       dry_run=args.dry_run,
                       package_set=pkg_set,
                       package_year=year,
                       mandatory_pkg=args.mandatory,
                       optional_pkg=args.optional,
                       caching_server=cache_server,
                       files_process=files_to_process,
                       jss_mode=jss_output_mode,
                       dmg_path=build_dmg)

    loops.main_processor()

if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        sys.exit()
