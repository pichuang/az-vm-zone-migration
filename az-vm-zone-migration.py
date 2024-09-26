#!/usr/bin/env python3
# pylint: disable=line-too-long, broad-exception-caught

import csv
import argparse
import sys
import subprocess
import logging
from datetime import datetime
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.models import Snapshot
import azure.core.exceptions

# Parse command-line arguments
parser = argparse.ArgumentParser(description='Azure VM Zone Level Migration Script')
parser.add_argument('--subscription-id', required=True, help='Azure subscription ID')
parser.add_argument('--csv-file', required=True, help='Path to the CSV file')
parser.add_argument('--check', action='store_true', help='Only check VM information without performing migration')
parser.add_argument('--debug', action='store_true', help='Enable debug output')

# If no arguments are provided, show help
if len(sys.argv) == 1:
    parser.print_help(sys.stderr)
    sys.exit(1)

args = parser.parse_args()

# Set up logging
log_level = logging.DEBUG if args.debug else logging.INFO
logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])

# Adjust logging level for specific loggers
logging.getLogger('azure.identity').setLevel(logging.WARNING)
logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.WARNING)

def check_azure_login():
    """
    Checks if the user is logged in to Azure using the Azure CLI.

    :raises SystemExit: If the user is not logged in or Azure CLI is not installed.
    """
    try:
        result = subprocess.run(['az', 'account', 'show'], capture_output=True, text=True, check=True) # pylint: disable=unused-variable
    except subprocess.CalledProcessError:
        logging.error("You are not logged in to Azure. Please run 'az login' to log in.")
        sys.exit(1)
    except FileNotFoundError:
        logging.error("Azure CLI is not installed. Please install it and log in using 'az login'.")
        sys.exit(1)

# Initialize Azure client
credential = DefaultAzureCredential()

# Check Azure login
check_azure_login()

subscription_id = args.subscription_id
csv_file_path = args.csv_file
check_only = args.check

compute_client = ComputeManagementClient(credential, subscription_id)

def read_csv(file_path):
    """
    Reads a CSV file and returns a list of dictionaries representing each row.

    :param file_path: Path to the CSV file.
    :return: List of dictionaries containing CSV data.
    :raises SystemExit: If the file is not found.
    """
    try:
        with open(file_path, mode='r', encoding='utf-8-sig') as file:
            csv_reader = csv.DictReader(file)
            return [row for row in csv_reader]
    except FileNotFoundError as e:
        logging.error("Error: %s", e)
        sys.exit(1)

def check_vm_exists(resource_group, vm_name):
    """
    Checks if a VM exists in the specified resource group and displays its SKU information.

    :param resource_group: Name of the resource group.
    :param vm_name: Name of the VM.
    :return: VM object if exists, None otherwise.
    :raises Exception: If an error occurs while checking the VM.
    """
    try:
        vm = compute_client.virtual_machines.get(resource_group, vm_name)
        vm_size = vm.hardware_profile.vm_size
        logging.info("VM '%s' in resource group '%s' has SKU: %s", vm_name, resource_group, vm_size)
        return vm
    except Exception as e:
        if 'ResourceNotFound' in str(e):
            logging.warning("The VM '%s' in resource group '%s' was not found. Please check the resource group and VM name.", vm_name, resource_group)
        else:
            logging.error("An error occurred while checking VM '%s' in '%s': %s", vm_name, resource_group, e)
        return None

def list_vm_disks(vm):
    """
    Lists all disks attached to the specified VM.

    :param vm: The VM object.
    """
    os_disk = vm.storage_profile.os_disk
    logging.info("OS Disk Name: %s, Resource ID: %s", os_disk.name, os_disk.managed_disk.id)
    for disk in vm.storage_profile.data_disks:
        logging.info("Data Disk Name: %s, Resource ID: %s", disk.name, disk.managed_disk.id)

def create_snapshot(resource_group, disk_name, disk_id, location, storage_type):
    """
    Creates a snapshot of the specified disk.

    :param resource_group: Name of the resource group.
    :param disk_name: Name of the disk.
    :param disk_id: Resource ID of the disk.
    :param location: Location of the disk.
    :param storage_type: Storage type of the disk.
    """
    try:
        snapshot_name = "%s-%s" % (disk_name, datetime.now().strftime('%Y%m%d%H%M%S'))
        logging.info("Creating snapshot for %s as %s", disk_name, snapshot_name)

        snapshot = Snapshot(
            location=location,
            creation_data={
                'create_option': 'Copy',
                'source_resource_id': disk_id
            },
            #XXX: Hardcoded storage type for snapshots
            #Message: SKU StandardSSD_ZRS is not supported for resource type Snapshot in this region. Supported SKUs for this region are Premium_LRS,Standard_LRS,Standard_ZRS
            # sku={'name': storage_type}
            sku={'name': 'Standard_ZRS'}
        )

        compute_client.snapshots.begin_create_or_update(resource_group, snapshot_name, snapshot)
    except azure.core.exceptions.ResourceNotFoundError:
        logging.error("Error: Resource %s with ID %s not found in %s.", disk_name, disk_id, resource_group)

def delete_vm(resource_group, vm_name, zones):
    """
    Deletes the specified VM and waits for completion.

    :param resource_group: Name of the resource group.
    :param vm_name: Name of the VM.
    :param zones: Zones of the VM.
    """
    logging.info("Deleting VM %s in %s with zones %s", vm_name, resource_group, zones)
    delete_operation = compute_client.virtual_machines.begin_delete(resource_group, vm_name)
    delete_operation.result()  # Wait for the operation to complete

def create_vm(resource_group, vm_name, zone, os_disk_id, data_disks, network_interface_id, vm_size, location, os_type):
    """
    Creates a new VM in the specified zone using existing disks.

    :param resource_group: Name of the resource group.
    :param vm_name: Name of the VM.
    :param zone: Desired zone for the VM.
    :param os_disk_id: Resource ID of the OS disk.
    :param data_disks: List of data disk resource IDs.
    :param network_interface_id: Resource ID of the network interface.
    :param vm_size: Size of the VM.
    :param os_type: OS type of the VM.
    """
    try:
        logging.info("Creating VM %s in %s at zone %s", vm_name, resource_group, zone)
        compute_client.virtual_machines.begin_create_or_update(
            resource_group,
            vm_name,
            {
                'location': location,
                'storage_profile': {
                    'os_disk': {
                        'managed_disk': {'id': os_disk_id},
                        'create_option': 'Attach',
                        'os_type': os_type
                    },
                    'data_disks': [{'managed_disk': {'id': disk_id}, 'create_option': 'Attach'} for disk_id in data_disks]
                },
                'hardware_profile': {
                    'vm_size': vm_size
                },
                'network_profile': {
                    'network_interfaces': [{'id': network_interface_id}]
                },
                'zones': [zone]
            }
        )
    except azure.core.exceptions.ResourceExistsError as e:
        if 'SkuNotAvailable' in str(e):
            logging.warning("The requested VM size '%s' is not available in location '%s'. Please try another size or location.", vm_size, location)
        else:
            logging.error("An error occurred while creating VM '%s': %s", vm_name, e)

def check_sku_availability(location, vm_size):
    """
    Checks if the specified VM size is available in the given location.

    :param location: Location to check for availability.
    :param vm_size: VM size to check.
    :return: True if available, False otherwise.
    """
    try:
        available = is_sku_available(location, vm_size)
        return available
    except Exception as e:
        logging.error("Error checking SKU availability: %s", e)
        return False

def is_sku_available(location, vm_size):
    """
    Checks if the specified VM size is available in the given location.

    :param location: Location to check for availability.
    :param vm_size: VM size to check.
    :return: True if available, False otherwise.
    """
    try:
        #compute_client = ComputeManagementClient(credential, subscription_id)
        skus = compute_client.resource_skus.list()
        for sku in skus:
            if sku.name == vm_size and location in sku.locations:
                return True
        return False
    except Exception as e:
        logging.error("Error checking SKU availability: %s", e)
        return False

def start_vm(resource_group, vm_name):
    """
    Starts the specified VM.

    :param resource_group: Name of the resource group.
    :param vm_name: Name of the VM.
    """
    logging.info("Starting VM %s in %s", vm_name, resource_group)
    compute_client.virtual_machines.begin_start(resource_group, vm_name)

def main():
    """
    Main function to process the CSV file and perform VM migration operations.
    """
    csv_data = read_csv(csv_file_path)
    for row in csv_data:
        source_rg = row['#Source Resource Group Name']
        source_vm = row['Source VM Name']
        source_os_type = row['Source OS Type'].strip().lower()
        desired_rg = row['Desired Resource Group Name']
        desired_vm = row['Desired VM Name']
        desired_zone = row['Desired Zone']

        os_type = 'Linux' if 'linux' in source_os_type else 'Windows'

        vm = check_vm_exists(source_rg, source_vm)
        if vm:
            logging.info("VM %s exists in %s with zone %s", source_vm, source_rg, vm.zones)
            list_vm_disks(vm)

            # Check if the desired zone is the same as the current zone
            if desired_zone in vm.zones:
                logging.warning("The desired zone '%s' is the same as the current zone. No migration needed.", desired_zone)
                continue

            if check_only:
                continue

            # Check SKU availability before proceeding
            if not check_sku_availability(vm.location, vm.hardware_profile.vm_size):
                logging.warning("The requested VM size '%s' is not available in location '%s'.", vm.hardware_profile.vm_size, vm.location)
                continue

            try:
                os_disk_storage_type = vm.storage_profile.os_disk.managed_disk.storage_account_type
                create_snapshot(source_rg, vm.storage_profile.os_disk.name, vm.storage_profile.os_disk.managed_disk.id, vm.location, os_disk_storage_type)
                for disk in vm.storage_profile.data_disks:
                    create_snapshot(source_rg, disk.name, disk.managed_disk.id, vm.location, disk.managed_disk.storage_account_type)
                os_disk_id = vm.storage_profile.os_disk.managed_disk.id
                data_disks = [disk.managed_disk.id for disk in vm.storage_profile.data_disks]
                network_interface_id = vm.network_profile.network_interfaces[0].id
                vm_size = vm.hardware_profile.vm_size
            except Exception as e:
                logging.error("Error occurred: %s", e)
                sys.exit(1)

            delete_vm(source_rg, source_vm, vm.zones)
            create_vm(desired_rg, desired_vm, desired_zone, os_disk_id, data_disks, network_interface_id, vm_size, vm.location, os_type)
            start_vm(desired_rg, desired_vm)
            list_vm_disks(vm)
            logging.info("-" * 40)
            # Verify the new VM

if __name__ == "__main__":
    main()
