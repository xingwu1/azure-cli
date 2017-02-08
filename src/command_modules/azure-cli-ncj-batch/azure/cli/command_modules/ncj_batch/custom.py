# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os

from azure.mgmt.batch.models import (BatchAccountCreateParameters,
                                     AutoStorageBaseProperties,
                                     UpdateApplicationParameters)

from azure.batch.models import (PoolAddParameter, CloudServiceConfiguration, VirtualMachineConfiguration,
                                ImageReference, PoolInformation, JobAddParameter,
                                JobConstraints, TaskConstraints, PoolUpdatePropertiesParameter,
                                StartTask)
from azure.cli.command_modules.batch._file_utils import FileUtils
import azure.cli.core._logging as _logging

logger = _logging.get_az_logger(__name__)

# NCJ custom commands

def create_pool(client, json_file=None, pool_id=None, vm_size=None, target_dedicated=None, #pylint:disable=too-many-arguments, W0613
                auto_scale_formula=None, os_family=None, image_publisher=None,
                image_offer=None, image_sku=None, node_agent_sku_id=None, resize_timeout=None,
                start_task_cmd=None, certificate_references=None,
                application_package_references=None, metadata=None, **kwarg):
    if json_file:
        with open(json_file) as f:
            json_obj = json.load(f)
            pool = client._deserialize('PoolAddParameter', json_obj) #pylint:disable=W0212
            if pool is None:
                raise ValueError("JSON file '{}' is not in correct format.".format(json_file))
    else:
        pool = PoolAddParameter(pool_id, vm_size=vm_size)
        if target_dedicated is not None:
            pool.target_dedicated = target_dedicated
            pool.enable_auto_scale = False
        else:
            pool.auto_scale_formula = auto_scale_formula
            pool.enable_auto_scale = True

        if os_family:
            pool.cloud_service_configuration = CloudServiceConfiguration(os_family)
        else:
            pool.virtual_machine_configuration = VirtualMachineConfiguration(
                ImageReference(image_publisher, image_offer, image_sku),
                node_agent_sku_id)

        if start_task_cmd:
            pool.start_task = StartTask(start_task_cmd)
        if resize_timeout:
            pool.resize_timeout = resize_timeout

        if metadata:
            pool.metadata = metadata
        if certificate_references:
            pool.certificate_references = certificate_references
        if application_package_references:
            pool.application_package_references = application_package_references

    client.add(pool=pool)
    return client.get(pool.id)

create_pool.__doc__ = PoolAddParameter.__doc__


def create_job(client, json_file=None, job_id=None, pool_id=None, priority=None, #pylint:disable=too-many-arguments, W0613
               max_wall_clock_time=None, max_task_retry_count=None,
               metadata=None, **kwarg):
    if json_file:
        with open(json_file) as f:
            json_obj = json.load(f)
            job = client._deserialize('JobAddParameter', json_obj) #pylint:disable=W0212
            if job is None:
                raise ValueError("JSON file '{}' is not in correct format.".format(json_file))
    else:
        pool = PoolInformation(pool_id=pool_id)
        job = JobAddParameter(job_id, pool, priority=priority)
        if max_wall_clock_time is not None or max_task_retry_count is not None:
            constraints = JobConstraints(max_wall_clock_time=max_wall_clock_time,
                                         max_task_retry_count=max_task_retry_count)
            job.constraints = constraints

        if metadata:
            job.metadata = metadata

    client.add(job)
    return client.get(job.id)

create_job.__doc__ = JobAddParameter.__doc__ + "\n" + JobConstraints.__doc__


def upload_file(client, resource_group_name, account_name,
                local_path, file_group, remote_path=None, flatten=None):
    """Upload local file or directory of files to storage"""
    file_utils = FileUtils(client, resource_group_name, account_name)
    blob_client = file_utils.resolve_storage_account(client, resource_group_name, account_name)
    path, files = file_utils.resolve_file_paths(local_path)
    if files.count > 0:
        for file in files:
            file_name = os.path.relpath(file, path)
            file_utils.upload_blob(file, file_group, file_name, blob_client,
                                   remote_path=remote_path, flatten=flatten)
    else:
        raise ValueError('No files or directories found matching local path {}'.format(local_path))


def download_file(client, resource_group_name, account_name,
                local_path, file_group, remote_path=None, flatten=None):
    pass
