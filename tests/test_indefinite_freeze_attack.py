#!/usr/bin/env python

"""
<Program Name>
  test_indefinite_freeze_attack.py

<Author>
  Konstantin Andrianov.

<Started>
  March 10, 2012.

  April 1, 2014.
    Refactored to use the 'unittest' module (test conditions in code, rather
    than verifying text output), use pre-generated repository files, and
    discontinue use of the old repository tools. -vladimir.v.diaz

  March 9, 2016.
    Additional test added relating to issue:
    https://github.com/theupdateframework/tuf/issues/322
    If a metadata file is not updated (no indication of a new version
    available), the expiration of the pre-existing, locally trusted metadata
    must still be detected. This additional test complains if such does not
    occur, and accompanies code in tuf.client.updater:refresh() to detect it.
    -sebastien.awwad

<Copyright>
  See LICENSE for licensing information.

<Purpose>
  Simulate an indefinite freeze attack.  In an indefinite freeze attack,
  attacker is able to respond to client's requests with the same, outdated
  metadata without the client being aware.
"""

# Help with Python 3 compatibility, where the print statement is a function, an
# implicit relative import is invalid, and the '/' operator performs true
# division.  Example:  print 'hello world' raises a 'SyntaxError' exception.
from __future__ import print_function
from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import os
import random
import time
import tempfile
import shutil
import json
import subprocess
import logging
import sys

# 'unittest2' required for testing under Python < 2.7.
if sys.version_info >= (2, 7):
  import unittest

else:
  import unittest2 as unittest 

import tuf.tufformats
import tuf.util
import tuf.log
import tuf.client.updater as updater
import tuf.repository_tool as repo_tool
import tuf.unittest_toolbox as unittest_toolbox
import tuf.roledb
import tuf.keydb

import six

# The repository tool is imported and logs console messages by default.  Disable
# console log messages generated by this unit test.
repo_tool.disable_console_log_messages()

logger = logging.getLogger('tuf.test_indefinite_freeze_attack')


class TestIndefiniteFreezeAttack(unittest_toolbox.Modified_TestCase):

  @classmethod
  def setUpClass(cls):
    # setUpClass() is called before any of the test cases are executed.
    
    # Create a temporary directory to store the repository, metadata, and target
    # files.  'temporary_directory' must be deleted in TearDownModule() so that
    # temporary files are always removed, even when exceptions occur. 
    cls.temporary_directory = tempfile.mkdtemp(dir=os.getcwd())
    
    # Launch a SimpleHTTPServer (serves files in the current directory).
    # Test cases will request metadata and target files that have been
    # pre-generated in 'tuf/tests/repository_data', which will be served by the
    # SimpleHTTPServer launched here.  The test cases of this unit test assume 
    # the pre-generated metadata files have a specific structure, such
    # as a delegated role 'targets/role1', three target files, five key files,
    # etc.
    cls.SERVER_PORT = random.randint(30000, 45000)
    command = ['python', 'simple_server.py', str(cls.SERVER_PORT)]
    cls.server_process = subprocess.Popen(command, stderr=subprocess.PIPE)
    logger.info('Server process started.')
    logger.info('Server process id: '+str(cls.server_process.pid))
    logger.info('Serving on port: '+str(cls.SERVER_PORT))
    cls.url = 'http://localhost:'+str(cls.SERVER_PORT) + os.path.sep

    # NOTE: Following error is raised if a delay is not applied:
    # <urlopen error [Errno 111] Connection refused>
    time.sleep(.8)



  @classmethod 
  def tearDownClass(cls):
    # tearDownModule() is called after all the test cases have run.
    # http://docs.python.org/2/library/unittest.html#class-and-module-fixtures
   
    # Remove the temporary repository directory, which should contain all the
    # metadata, targets, and key files generated of all the test cases.
    shutil.rmtree(cls.temporary_directory)
    
    # Kill the SimpleHTTPServer process.
    if cls.server_process.returncode is None:
      logger.info('Server process '+str(cls.server_process.pid)+' terminated.')
      cls.server_process.kill()



  def setUp(self):
    # We are inheriting from custom class.
    unittest_toolbox.Modified_TestCase.setUp(self)
  
    # Copy the original repository files provided in the test folder so that
    # any modifications made to repository files are restricted to the copies.
    # The 'repository_data' directory is expected to exist in 'tuf/tests/'.
    original_repository_files = os.path.join(os.getcwd(), 'repository_data') 
    temporary_repository_root = \
      self.make_temp_directory(directory=self.temporary_directory)
  
    # The original repository, keystore, and client directories will be copied
    # for each test case. 
    original_repository = os.path.join(original_repository_files, 'repository')
    original_client = os.path.join(original_repository_files, 'client')
    original_keystore = os.path.join(original_repository_files, 'keystore')
    
    # Save references to the often-needed client repository directories.
    # Test cases need these references to access metadata and target files. 
    self.repository_directory = \
      os.path.join(temporary_repository_root, 'repository')
    self.client_directory = os.path.join(temporary_repository_root, 'client')
    self.keystore_directory = os.path.join(temporary_repository_root, 'keystore')
    
    # Copy the original 'repository', 'client', and 'keystore' directories
    # to the temporary repository the test cases can use.
    shutil.copytree(original_repository, self.repository_directory)
    shutil.copytree(original_client, self.client_directory)
    shutil.copytree(original_keystore, self.keystore_directory)
    
    # Set the url prefix required by the 'tuf/client/updater.py' updater.
    # 'path/to/tmp/repository' -> 'localhost:8001/tmp/repository'. 
    repository_basepath = self.repository_directory[len(os.getcwd()):]
    url_prefix = \
      'http://localhost:' + str(self.SERVER_PORT) + repository_basepath 
    
    # Setting 'tuf.conf.repository_directory' with the temporary client
    # directory copied from the original repository files.
    tuf.conf.repository_directory = self.client_directory 
    self.repository_mirrors = {'mirror1': {'url_prefix': url_prefix,
                                           'metadata_path': 'metadata',
                                           'targets_path': 'targets',
                                           'confined_target_dirs': ['']}}

    # Create the repository instance.  The test cases will use this client
    # updater to refresh metadata, fetch target files, etc.
    self.repository_updater = updater.Updater('test_repository',
                                              self.repository_mirrors)


  def tearDown(self):
    # Modified_TestCase.tearDown() automatically deletes temporary files and
    # directories that may have been created during each test case.
    unittest_toolbox.Modified_TestCase.tearDown(self)
    tuf.roledb.clear_roledb(clear_all=True)
    tuf.keydb.clear_keydb(clear_all=True)


  def test_without_tuf(self):
    # Without TUF, Test 1 and Test 2 are functionally equivalent, so we skip
    # Test 1 and only perform Test 2.
    #
    # Test 1: If we find that the timestamp acquired from a mirror indicates
    #         that there is no new snapshot file, and our current snapshot
    #         file is expired, is it recognized as such?
    # Test 2: If an expired timestamp is downloaded, is it recognized as such?


    # Test 2 Begin:
    #
    # 'timestamp.json' specifies the latest version of the repository files.  A
    # client should only accept the same version of this file up to a certain
    # point, or else it cannot detect that new files are available for
    # download.  Modify the repository's timestamp.json' so that it expires
    # soon, copy it over to the client, and attempt to re-fetch the same
    # expired version. 
    #
    # A non-TUF client (without a way to detect when metadata has expired) is
    # expected to download the same version, and thus the same outdated files.
    # Verify that the downloaded 'timestamp.json' contains the same file size
    # and hash as the one available locally.

    timestamp_path = os.path.join(self.repository_directory, 'metadata',
                                  'timestamp.json')

    timestamp_metadata = tuf.util.load_json_file(timestamp_path)
    expiry_time = time.time() - 10
    expires = tuf.tufformats.unix_timestamp_to_datetime(int(expiry_time))
    expires = expires.isoformat() + 'Z'
    timestamp_metadata['signed']['expires'] = expires 
    tuf.tufformats.check_signable_object_format(timestamp_metadata) 
    
    with open(timestamp_path, 'wb') as file_object:
      # Explicitly specify the JSON separators for Python 2 + 3 consistency.
      timestamp_content = \
        json.dumps(timestamp_metadata, indent=1, separators=(',', ': '),
                   sort_keys=True).encode('utf-8')
      file_object.write(timestamp_content)

    client_timestamp_path = os.path.join(self.client_directory,
                                         'timestamp.json')
    shutil.copy(timestamp_path, client_timestamp_path)
    
    length, hashes = tuf.util.get_file_details(timestamp_path)
    fileinfo = tuf.tufformats.make_fileinfo(length, hashes) 
    
    url_prefix = self.repository_mirrors['mirror1']['url_prefix']
    url_file = os.path.join(url_prefix, 'metadata', 'timestamp.json')
   
    six.moves.urllib.request.urlretrieve(url_file, client_timestamp_path)
    
    length, hashes = tuf.util.get_file_details(client_timestamp_path)
    download_fileinfo = tuf.tufformats.make_fileinfo(length, hashes)
    
    # Verify 'download_fileinfo' is equal to the current local file.
    self.assertEqual(download_fileinfo, fileinfo)


  def test_with_tuf(self):
    # Two tests are conducted here.
    #
    # Test 1: If we find that the timestamp acquired from a mirror indicates
    #         that there is no new snapshot file, and our current snapshot
    #         file is expired, is it recognized as such?
    # Test 2: If an expired timestamp is downloaded, is it recognized as such?


    # Test 1 Begin:
    #
    # Addresses this issue: https://github.com/theupdateframework/tuf/issues/322
    #
    # If time has passed and our snapshot or targets role is expired, and
    # the mirror whose timestamp we fetched doesn't indicate the existence of a
    # new snapshot version, we still need to check that it's expired and notify
    # the software update system / application / user. This test creates that
    # scenario. The correct behavior is to raise an exception.
    #
    # Background: Expiration checks (updater._ensure_not_expired) were
    # previously conducted when the metadata file was downloaded. If no new
    # metadata file was downloaded, no expiry check would occur. In particular, 
    # while root was checked for expiration at the beginning of each
    # updater.refresh() cycle, and timestamp was always checked because it was
    # always fetched, snapshot and targets were never checked if the user did 
    # not receive evidence that they had changed. This bug allowed a class of
    # freeze attacks.
    # That bug was fixed and this test tests that fix going forward.

    # Modify the timestamp file on the remote repository.  'timestamp.json'
    # must be properly updated and signed with 'repository_tool.py', otherwise
    # the client will reject it as invalid metadata.

    # Load the repository
    repository = repo_tool.load_repository(self.repository_directory)

    # Load the timestamp and snapshot keys, since we will be signing a new
    # timestamp and a new snapshot file.
    key_file = os.path.join(self.keystore_directory, 'timestamp_key') 
    timestamp_private = repo_tool.import_ed25519_privatekey_from_file(key_file,
                                                                  'password')
    repository.timestamp.load_signing_key(timestamp_private)
    key_file = os.path.join(self.keystore_directory, 'snapshot_key') 
    snapshot_private = repo_tool.import_ed25519_privatekey_from_file(key_file,
                                                                  'password')
    repository.snapshot.load_signing_key(snapshot_private)

    # Expire snapshot in 10s. This should be far enough into the future that we
    # haven't reached it before the first refresh validates timestamp expiry.
    # We want a successful refresh before expiry, then a second refresh after
    # expiry (which we then expect to raise an exception due to expired
    # metadata).
    expiry_time = time.time() + 10
    datetime_object = tuf.tufformats.unix_timestamp_to_datetime(int(expiry_time))

    repository.snapshot.expiration = datetime_object

    # Now write to the repository.
    repository.writeall()

    # And move the staged metadata to the "live" metadata.
    shutil.rmtree(os.path.join(self.repository_directory, 'metadata'))
    shutil.copytree(os.path.join(self.repository_directory, 'metadata.staged'),
                    os.path.join(self.repository_directory, 'metadata'))

    # Refresh metadata on the client. For this refresh, all data is not expired.
    logger.info('Test: Refreshing #1 - Initial metadata refresh occurring.')
    self.repository_updater.refresh()
    logger.info('Test: Refreshed #1 - Initial metadata refresh completed '
                'successfully. Now sleeping until snapshot metadata expires.')

    # Sleep until expiry_time ('repository.snapshot.expiration')
    time.sleep(max(0, expiry_time - time.time()))

    logger.info('Test: Refreshing #2 - Now trying to refresh again after local'
      ' snapshot expiry.')
    try:
      self.repository_updater.refresh() # We expect this to fail!

    except tuf.ssl_commons.exceptions.ExpiredMetadataError:
      logger.info('Test: Refresh #2 - failed as expected. Expired local'
                  ' snapshot case generated a tuf.ssl_commons.exceptions.ExpiredMetadataError'
                  ' exception as expected. Test pass.')
    
    # I think that I only expect tuf.ExpiredMetadata error here. A
    # NoWorkingMirrorError indicates something else in this case - unavailable
    # repo, for example.
    else:
      self.fail('TUF failed to detect expired stale snapshot metadata. Freeze'
        ' attack successful.')




    # Test 2 Begin:
    #
    # 'timestamp.json' specifies the latest version of the repository files.
    # A client should only accept the same version of this file up to a certain
    # point, or else it cannot detect that new files are available for download.
    # Modify the repository's 'timestamp.json' so that it is about to expire,
    # copy it over the to client, wait a moment until it expires, and attempt to
    # re-fetch the same expired version.

    # The same scenario as in test_without_tuf() is followed here, except with
    # a TUF client. The TUF client performs a refresh of top-level metadata,
    # which includes 'timestamp.json', and should detect a freeze attack if
    # the repository serves an outdated 'timestamp.json'.
    
    # Modify the timestamp file on the remote repository.  'timestamp.json'
    # must be properly updated and signed with 'repository_tool.py', otherwise
    # the client will reject it as invalid metadata.  The resulting
    # 'timestamp.json' should be valid metadata, but expired (as intended).
    repository = repo_tool.load_repository(self.repository_directory)
 
    key_file = os.path.join(self.keystore_directory, 'timestamp_key')
    timestamp_private = repo_tool.import_ed25519_privatekey_from_file(key_file,
                                                                  'password')

    repository.timestamp.load_signing_key(timestamp_private)
    
    # Set timestamp metadata to expire soon.
    # We cannot set the timestamp expiration with
    # 'repository.timestamp.expiration = ...' with already-expired timestamp
    # metadata because of consistency checks that occur during that assignment.
    expiry_time = time.time() + 1
    datetime_object = tuf.tufformats.unix_timestamp_to_datetime(int(expiry_time))
    repository.timestamp.expiration = datetime_object
    repository.writeall()
    
    # Move the staged metadata to the "live" metadata.
    shutil.rmtree(os.path.join(self.repository_directory, 'metadata'))
    shutil.copytree(os.path.join(self.repository_directory, 'metadata.staged'),
                    os.path.join(self.repository_directory, 'metadata'))

    # Wait just long enough for the timestamp metadata (which is now both on
    # the repository and on the client) to expire.
    time.sleep(max(0, expiry_time - time.time()))

    # Try to refresh top-level metadata on the client. Since we're already past
    # 'repository.timestamp.expiration', the TUF client is expected to detect
    # that timestamp metadata is outdated and refuse to continue the update
    # process.
    try:
      self.repository_updater.refresh() # We expect NoWorkingMirrorError.
    
    except tuf.ssl_commons.exceptions.NoWorkingMirrorError as e:
      # NoWorkingMirrorError indicates that we did not find valid, unexpired
      # metadata at any mirror. That exception class preserves the errors from
      # each mirror. We now assert that for each mirror, the particular error
      # detected was that metadata was expired (the timestamp we manually
      # expired).
      for mirror_url, mirror_error in six.iteritems(e.mirror_errors):
        self.assertTrue(isinstance(mirror_error, tuf.ssl_commons.exceptions.ExpiredMetadataError))
    
    else:
      self.fail('TUF failed to detect expired, stale timestamp metadata.'
        ' Freeze attack successful.')


if __name__ == '__main__':
  unittest.main()
