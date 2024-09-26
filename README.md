# AZ VM Zone Level Migration

This project provides a script for migrating virtual machines across zones in Azure.

## Prerequisites

- Azure Subscription
- Azure CLI installed and logged in
- Python 3.x
- Cloud Shell environment

## Installation

1. **Launch Cloud Shell**

   Log in to the [Azure Portal](https://portal.azure.com) and launch Cloud Shell.

2. **Clone the Project**

   Run the following command in Cloud Shell to clone the project:

   ```bash
   git clone <YOUR_REPOSITORY_URL>
   cd az-vm-zone-migration
   ```

3. **Install Dependencies**

   Install the required Python packages using:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. **Prepare the CSV File**

   Prepare your CSV file according to the format in `vm-migration.csv.example` and upload it to Cloud Shell.

2. **Run the Script**

   Execute the script using the following command:

   ```bash
   python az-vm-zone-migration.py --subscription-id <YOUR_SUBSCRIPTION_ID> --csv-file <YOUR_CSV_FILE_PATH> [--check] [--debug]
   ```

   - `--subscription-id`: Your Azure subscription ID.
   - `--csv-file`: Path to the CSV file.
   - `--check`: Only check VM information without performing migration.
   - `--debug`: Enable debug output.

## Notes

- Ensure you have logged in to Azure CLI using `az login`.
- Verify that the resource group and VM names in the CSV file are correct.
