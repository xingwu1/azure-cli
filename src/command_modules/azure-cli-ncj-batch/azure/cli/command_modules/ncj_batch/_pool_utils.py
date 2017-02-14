# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum

class PoolOperatingSystemFlavor(Enum):
    WINDOWS = 'windows'
    LINUX = 'linux'


def get_pool_target_os_type(pool):
    image_publisher = None
    if pool.virtual_machine_configuration:
        image_publisher = pool.virtual_machine_configuration.image_reference.publisher

    os_flavor = PoolOperatingSystemFlavor.WINDOWS
    if image_publisher:
        os_flavor = PoolOperatingSystemFlavor.WINDOWS \
            if image_publisher.find('MicrosoftWindowsServer') \
            else PoolOperatingSystemFlavor.LINUX

    return os_flavor
