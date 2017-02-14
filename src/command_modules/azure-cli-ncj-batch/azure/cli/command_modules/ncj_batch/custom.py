# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os

from azure.batch.models import (
    PoolAddParameter, CloudServiceConfiguration, VirtualMachineConfiguration,
    ImageReference, PoolInformation, JobAddParameter,
    JobConstraints, StartTask)
from azure.cli.command_modules.ncj_batch._file_utils import (
    FileUtils, resolve_file_paths, upload_blob)
import azure.cli.command_modules.ncj_batch._template_utils as template_utils
import azure.cli.command_modules.ncj_batch._pool_utils as pool_utils
import azure.cli.core.azlogging as azlogging

logger = azlogging.get_az_logger(__name__)

# NCJ custom commands

def create_pool(client, template=None, parameters=None, json_file=None,  # pylint:disable=too-many-arguments, too-many-locals, W0613
                id=None, vm_size=None, target_dedicated=None, auto_scale_formula=None,  # pylint: disable=redefined-builtin
                enable_inter_node_communication=False, os_family=None, image=None,
                node_agent_sku_id=None, resize_timeout=None, start_task_command_line=None,
                start_task_resource_files=None, start_task_run_elevated=False,
                start_task_wait_for_success=False, certificate_references=None,
                application_package_references=None, metadata=None):
    # pylint: disable=too-many-branches, too-many-statements
    if template or json_file:
        if template:
            logger.warning('You are using an experimental feature {Pool Template}.')
            expanded_pool_object = template_utils.expand_template(template, parameters)
            if not 'pool' in expanded_pool_object:
                raise ValueError('Missing pool element in the template.')
            if not 'properties' in expanded_pool_object['pool']:
                raise ValueError('Missing pool properties element in the template.')
            # bulid up the jsonFile object to hand to the batch service.
            json_obj = expanded_pool_object['pool']['properties']
        else:
            with open(json_file) as f:
                json_obj = json.load(f)
            # validate the json file
            pool = client._deserialize('PoolAddParameter', json_obj)  #pylint:disable=W0212
            if pool is None:
                raise ValueError("JSON file '{}' is not in correct format.".format(json_file))

        # Handle package manangement
        if 'packageReferences' in json_obj:
            logger.warning('You are using an experimental feature {Package Management}.')
            pool_os_flavor = pool_utils.get_pool_target_os_type(json_obj)
            cmds = [template_utils.process_pool_package_references(json_obj)]
            # Update the start up command
            json_obj['startTask'] = template_utils.construct_setup_task(
                json_obj['startTask'] if 'startTask' in json_obj else None,
                cmds, pool_os_flavor)

        # Handle any special post-processing steps.
        # - Resource Files
        # - etc
        json_obj = template_utils.post_processing(json_obj)

        # Batch Shipyard integration
        if 'clientExtensions' in json_obj and 'dockerOptions' in json_obj['clientExtensions']:
            logger.warning('You are using an experimental feature {Batch Shipyard}.')
            # batchShipyardUtils.createPool(json_obj, options, cli)
            # return

        # We deal all NCJ work with pool, now convert back to original type
        pool = client._deserialize('PoolAddParameter', json_obj)  #pylint:disable=W0212

    else:
        if not id:
            raise ValueError('Need either template, json_file, or id')

        pool = PoolAddParameter(id, vm_size=vm_size)
        if target_dedicated is not None:
            pool.target_dedicated = target_dedicated
            pool.enable_auto_scale = False
        else:
            pool.auto_scale_formula = auto_scale_formula
            pool.enable_auto_scale = True
        pool.enable_inter_node_communication = enable_inter_node_communication

        if os_family:
            pool.cloud_service_configuration = CloudServiceConfiguration(os_family)
        else:
            if image:
                version = 'latest'
                try:
                    publisher, offer, sku = image.split(':', 2)
                except ValueError:
                    message = ("Incorrect format for VM image URN. Should be in the format: \n"
                               "'publisher:offer:sku[:version]'")
                    raise ValueError(message)
                try:
                    sku, version = sku.split(':', 1)
                except ValueError:
                    pass
                pool.virtual_machine_configuration = VirtualMachineConfiguration(
                    ImageReference(publisher, offer, sku, version),
                    node_agent_sku_id)

        if start_task_command_line:
            pool.start_task = StartTask(start_task_command_line)
            pool.start_task.run_elevated = start_task_run_elevated
            pool.start_task.wait_for_success = start_task_wait_for_success
            pool.start_task.resource_files = start_task_resource_files
        if resize_timeout:
            pool.resize_timeout = resize_timeout

        if metadata:
            pool.metadata = metadata
        if certificate_references:
            pool.certificate_references = certificate_references
        if application_package_references:
            pool.application_package_references = application_package_references

    # TODO: add _handle_exception
    client.pool.add(pool)
    return client.pool.get(pool.id)

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


def upload_file(client, resource_group_name, account_name,  # pylint: disable=too-many-arguments
                local_path, file_group, remote_path=None, flatten=None):
    """Upload local file or directory of files to storage"""
    file_utils = FileUtils(client, resource_group_name, account_name)
    blob_client = file_utils.resolve_storage_account()
    path, files = resolve_file_paths(local_path)
    if len(files) > 0:
        for f in files:
            file_name = os.path.relpath(f, path)
            upload_blob(f, file_group, file_name, blob_client,
                        remote_path=remote_path, flatten=flatten)
    else:
        raise ValueError('No files or directories found matching local path {}'.format(local_path))


def download_file(client, resource_group_name, account_name,  # pylint: disable=too-many-arguments, unused-argument
                  local_path, file_group, remote_path=None, flatten=None):  # pylint: disable=unused-argument
    pass
