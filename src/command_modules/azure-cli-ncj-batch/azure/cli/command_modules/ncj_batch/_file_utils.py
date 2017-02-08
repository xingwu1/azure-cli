# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import re
import glob
import hashlib
import datetime
import copy
from six.moves.urllib.parse import urlsplit  # pylint: disable=import-error

from azure.mgmt.storage import StorageManagementClient
from azure.storage import CloudStorageAccount
from azure.storage.blob import BlobPermissions, BlockBlobService

from azure.cli.core.commands.client_factory import get_mgmt_service_client
import azure.cli.core.azlogging as azlogging

logger = azlogging.get_az_logger(__name__)


class FileUtils:

    STRIP_PATH = r"^[/\\]+|[/\\]+$"
    GROUP_PREFIX = 'fgrp-'
    MAX_GROUP_LENGTH = 63 - len(GROUP_PREFIX)
    MAX_FILE_SIZE = 50000 * 4 * 1024 * 1024
    PARALLEL_OPERATION_THREAD_COUNT = 5
    SAS_PERMISSIONS = BlobPermissions.READ  # Read permission
    SAS_EXPIRY_DAYS = 7  # 7 days

    def __init__(self, resource_group_name, account_name):
        self.resource_file_cache = {}
        self.resource_group_name = resource_group_name
        self.account_name = account_name
        self.resolved_storage_client = None


    def filter_resource_cache(self, container, prefix):
        """Return all blob refeferences in a container cache that meet a prefix requirement."""

        filtered = []
        for blob in self.resource_file_cache[container]:
            if not prefix:
                filtered.append(blob)
            elif blob.file_path.startswith(prefix):
                filtered.append(blob)
        return filtered



#   if (!resourceFileCache[container]) {
#     resourceFileCache[container] = [];
#     var operation = storageUtil.getStorageOperation(blobService, storageUtil.OperationType.Blob, 'listAllBlobs');
#     var storageOptions = storageUtil.getStorageOperationDefaultOption();
#     var blobs = storageUtil.performStorageOperation(operation, _, container, storageOptions);
#     blobs.forEach_(_, 1, function(_, blob) {
#       var blobSas =  source.fileGroup ? batchFileUtils.generateSasToken(blob, container, blobService) : batchFileUtils.constructSasUrl(blob, url.parse(source.containerUrl));
#       var fileName = pathUtil.basename(blob.name);
#       var fileNameOnly = fileName;
#       if (fileName.indexOf('.') >= 0) { 
#         fileNameOnly = fileName.substr(0, fileName.lastIndexOf('.'));
#       }
#       resourceFileCache[container].push({  url : blobSas, filePath : blob.name, fileName : fileName, fileNameWithoutExtension : fileNameOnly });
#     });
#   }
#   return batchFileUtils.filterResourceCache(container, source.prefix, _);
# };



    def list_container_contents(self, source, container, blob_service):
        """List blob references in container."""
        if not self.resource_file_cache[container]:
            self.resource_file_cache[container] = []
        blobs = blob_service.list_blobs(container)
        for blob in blobs:
            blob_sas = self.generate_sas_token(blob, container, blob_service) \
                if source.file_group else \
                    self.construct_sas_url(blob, urlsplit(source.container_url))
            file_name = os.path.basename(blob.name)
            file_name_only = os.path.splitext(file_name)[0]
            self.resource_file_cache[container].append(
                {'url' : blob_sas,
                 'filePath' : blob.name,
                 'fileName' : file_name,
                 'fileNameWithoutExtension' : file_name_only})
        return self.filter_resource_cache(container, source.prefix)

    def generate_sas_token(self, blob, container, blob_service):
        """Generate a blob URL with SAS token."""
        sas_token = blob_service.generate_blob_shared_access_signature(
            container, blob,
            permission=self.SAS_PERMISSIONS,
            start=datetime.datetime.utcnow(),
            expiry=datetime.datetime.utcnow() + datetime.timedelta(days=SAS_EXPIRY_DAYS))
        return blob_service.make_blob_url(container, blob, sas_token=sas_token)

    def construct_sas_url(self, blob, uri):
        """Make up blob URL with container URL"""
        newuri = copy.copy(uri)
        newuri.pathname = '{}/{}'.format(uri.path, blob.name)
        return newuri.geturl()

    def get_container_list(self, client, source, resource_group_name, account_name):
        """List blob references in container."""
        files = []
        storage_client = None
        container = None
        blobs = None
        is_auto_storage = False

        if source.fileGroup:
            # Input data stored in auto-storage
            storage_client = resolve_storage_account(client, resource_group_name, account_name)
            container = get_container_name(source.file_group)
            is_auto_storage = True
        elif source.container_url:
            uri = urlsplit.urlsplit(source.container_url)
            if not uri.query:
                raise ValueError('Invalid container url.')
            storage_account_name = uri.netloc.split('.')[0]
            sas_token = uri.query
            storage_client = BlockBlobService(account_name=storage_account_name,
                                              sas_token=sas_token)
            container = uri.pathname.split('/')[1]
        else:
            raise ValueError('Unknown source.')

        return self.list_container_contents(source, container, storage_client)


    def convert_blobs_to_resource_files(self, blobs, resource_properties, container, blob_service):
        """Convert a list of blobs to a list of ResourceFiles"""
        resource_files = []
        if not blobs or len(blobs) == 0:
            raise ValueError('No input data found with reference {}'.
                             format(resource_properties.source.prefix))

        if len(blobs.length) == 1 and blobs[0].file_path == resource_properties.source.prefix:
            # Single file reference: filePath should be treated as file path
            file_path = resource_properties.file_path \
                if resource_properties.file_path else blobs[0].file_path
            resource_files.append({
                # 'blobSource': blobs[0].url,
                'blobSource': self.generate_sas_token(blobs[0], container, blob_service),
                'filePath': file_path
            })
        else:
            # Multiple file reference: filePath should be treated as a directory
            base_file_path = ''
            if resource_properties.file_path:
                base_file_path = '{}/'.format(resource_properties.file_path.replace(STRIP_PATH, ''))

            for blob in blobs:
                file_path = '{}{}'.format(base_file_path, blob.name)
                resource_files.append({
                    'blobSource': self.generate_sas_token(blob, container, blob_service),
                    'filePath': file_path
                })

        # Add filemode to every resourceFile
        if resource_properties.file_mode:
            for f in resource_files:
                f.file_mode = resource_properties.file_mode

        return resource_files


    def resolve_resource_file(self, client, resource_file, resource_group_name, account_name):
        """Convert new resourceFile reference to server-supported reference"""
        if resource_file.blob_source:
            # Support original resourceFile reference
            if not resource_file.file_path:
                raise ValueError('Malformed ResourceFile: \'blobSource\' must '
                                'also have \'filePath\' attribute')
            return list(resource_file)

        if not resource_file.source:
            raise ValueError('Malformed ResourceFile: Must have either \'source\' or \'blobSource\'')

#   var storageClient = batchFileUtils.resolveStorageAccount(options, _);
#  +  var container;
#  +  var blobs;

    if resource_file.source.file_group:
        # Input data stored in auto-storage
    # container = batchFileUtils.getContainerName(resourceFile.source.fileGroup);
    #  blobs = batchFileUtils.listContainerContents(resourceFile.source, container, storageClient, _);

        storage_client = resolve_storage_account(client, resource_group_name, account_name)
        container = get_container_name(resource_file.source.file_group)
        blobs = list_container_contents(resource_file.source.prefix, container, storage_client)
        return convert_blobs_to_resource_files(blobs, resource_file, container, storage_client)
    elif resource_file.source.container_url:
        # TODO: Input data storage in arbitrary container
# +    var uri = url.parse(resourceFile.source.containerUrl);
#  +    container = uri.pathname.split('/')[1];
#  +    blobs = batchFileUtils.listContainerContents(resourceFile.source, container, storageClient, _);
#  +    return batchFileUtils.convertBlobsToResourceFiles(blobs, resourceFile, container, storageClient, _);
        raise ValueError('Not implemented')
    elif resource_file.source.url:
        # TODO: Input data from an arbitrary HTTP GET source
        raise ValueError('Not implemented')
    else:
        raise ValueError('Malformed ResourceFile')


def resolve_storage_account(client, resource_group_name, account_name):
    """Resolve Auto-Storage account from supplied Batch Account"""
    account = client.get(resource_group_name, account_name)
    if not account.auto_storage:
        raise ValueError('No linked auto-storage for account {}'.format(account_name))

    storage_account_info = account.auto_storage.storage_account_id.split('/')
    storage_resource_group = storage_account_info[4]
    storage_account = storage_account_info[8]

    storage_client = get_mgmt_service_client(StorageManagementClient)
    keys = storage_client.storage_accounts.list_keys(storage_resource_group, storage_account)
    storage_key = keys[0].value

    return CloudStorageAccount(storage_account, storage_key).create_block_blob_service()


def resolve_file_paths(local_path):
    """Generate list of files to upload and the relative directory"""
    local_path = re.sub(STRIP_PATH, "", local_path)
    files = []
    if local_path.index('*') > -1:
        # Supplied path is a pattern - relative directory will be the
        # path up to the first wildcard
        ref_dir = local_path.split('*')[0]
        local_path = os.path.dirname(re.sub(STRIP_PATH, "", ref_dir))
        files = glob.glob(local_path)
    else:
        if os.path.isdir(local_path):
            # Supplied path is a directory
            files = [os.path.join(local_path, f) for f in os.listdir(local_path)
                     if os.path.isfile(os.path.join(local_path, f))]
        elif os.path.isfile(local_path):
            # Supplied path is a file
            files.append(local_path)
            local_path = os.path.dirname(local_path)
    return local_path, files


def generate_container_name(file_group):
    """Generate valid container name from file group name."""

    file_group = file_group.lower()
    # Check for any chars that aren't 'a-z', '0-9' or '-'
    valid_chars = r'^[a-z0-9][-a-z0-9]*$'
    # Replace any underscores or double-hyphens with single hyphen
    underscores_and_hyphens = r'[_-]+'

    clean_group = re.sub(underscores_and_hyphens, '-', file_group)
    clean_group = clean_group.rstrip('-')
    if not re.match(valid_chars, clean_group):
        raise ValueError('File group name \'{}\' contains illegal characters. '
                         'File group names only support alphanumeric characters, '
                         'underscores and hyphens.'.format(file_group))

    if clean_group == file_group and len(file_group) <= MAX_GROUP_LENGTH:
        # If specified group name is clean, no need to add hash
        return file_group
    else:
        # If we had to transform the group name, add hash of original name
        hash_str = hashlib.sha1(file_group.encode()).hexdigest()
        new_group = '{}-{}'.format(clean_group, hash_str)
        if len(new_group) > MAX_GROUP_LENGTH:
            return '{}-{}'.format(clean_group[0:15], hash_str)
        return new_group


def get_container_name(file_group):
    """Get valid container name from file group name with prefix."""
    return '{}{}'.format(GROUP_PREFIX, generate_container_name(file_group))


def upload_blob(source, destination, file_name, blob_service, remote_path=None, flatten=None):
    """Upload the specified file to the specified container"""
    if not os.path.isfile(source):
        raise ValueError('Failed to locate file {}'.format(source))

    statinfo = os.stat(source)
    if statinfo.st_size > 50000 * 4 * 1024 * 1024:
        raise ValueError('The local file size {} exceeds the Azure blob size limit'.
                         format(statinfo.st_size))
    if flatten:
        # Flatten local directory structure
        file_name = os.path.basename(file_name)

    # Create upload container with sanitized file group name
    container_name = get_container_name(destination)
    blob_service.create_container(container_name)

    blob_name = file_name
    if remote_path:
        # Add any specified virtual directories
        blob_prefix = re.sub(STRIP_PATH, remote_path, '')
        blob_name = '{}/{}'.format(blob_prefix, re.sub(STRIP_PATH, file_name, ''))

#   var storageOptions = storageUtil.getStorageOperationDefaultOption();
#   storageOptions.parallelOperationThreadCount = PARALLEL_OPERATION_THREAD_COUNT;

#   //We want to validate the file as we upload, and only complete the operation
#   //if all the data transfers successfully
#   storageOptions.storeBlobContentMD5 = true;
#   storageOptions.useTransactionalMD5 = true;

#   //We store the lastmodified timestamp in order to prevent overwriting with
#   //out-dated or duplicate data. TODO: Investigate cleaner options for handling this.
#   var rounded = new Date(Math.round(fsStatus.mtime.getTime() / ROUND_DATE) * ROUND_DATE);
#   storageOptions.metadata = {'lastmodified': rounded.toISOString() };

#   var summary = new storage.BlobService.SpeedSummary(blobName);
#   storageOptions.speedSummary = summary;

    blob_name = blob_name.replace('\\', '/')
    metadata = None
    try:
        metadata = blob_service.get_blob_metadata(container_name, blob_name)
    except Exception:  # pylint: disable=broad-except
        # check notfound
        pass

#     if (props.metadata.lastmodified) {
#       var lastModified = new Date(props.metadata.lastmodified);
#       if (lastModified >= rounded){
#         logger.info(util.format($('File \'%s\' already exists and up-to-date - skipping'), blobName));
#         return;
#       }
#     }

#   var tips = util.format($('Uploading %s to blob %s in container %s'), sourcefile, blobName, containerName);
#   var printer = storageUtil.getSpeedPrinter(summary);
#   var intervalId = -1;
#   if (!logger.format().json) {
#     intervalId = setInterval(printer, 1000);
#   }
#   startProgress(tips);

    # Upload block blob
    # TODO: Get this uploading in parallel.
    # TODO: Investigate compression + chunking performance enhancement proposal.
    blob_service.create_blob_from_path(
        container_name=container_name,
        blob_name=blob_name,
        file_path=source,
        progress_callback=lambda c, t: None,
        metadata=metadata,
        validate_content=True,
        max_connections=PARALLEL_OPERATION_THREAD_COUNT)

