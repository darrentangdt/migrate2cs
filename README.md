% VMware to Apache CloudStack Migration
% Will Stevens
% 2016/03/30


HOWTO USE THE TOOL
------------------

Once everything is installed and `./settings.conf` has been configured, you can use the tool.  
\ 

### Start the migration server UI
``` bash
$ cd ~/migrate2cs
$ nohup python ui_server_vmware.py > logs/server.log 2>&1&
```
\ 

### Do a migration

- Navigate to: `http://MIGRATION_VM_IP:8787` (or whatever port was specified in the `[WEBSERVER]` section of the `./settings.conf`)
- On load, it will discover both the VMware and Apache CloudStack environments, so it will take 10-15 seconds to load.
- When the page loads, the Apache CloudStack details will be available in the dropdowns at the top and the VMware VMs will be listed below.
- You can click on the VM name or check the checkbox to expand it to show more details.
- To apply a specific Apache CloudStack configuration to a group of VMs, select the VMs by checking the associated check box and specify the Apache CloudStack details in the dropdowns, then click the `Apply to Selected VMs` button.
- You can review the Apache CloudStack details in the expanded view of the VMs.
- To begin the migration, make sure you have Apache CloudStack details applied to all the selected VMs, then click `Migrate Selected VMs`.  
\ 

### View migration progress

- The `Select and Migrate VMs` section will collapse and the `Migration Progress` section will open when the `Migrate Selected VMs` button is clicked.
- The textarea in this section will update with the migration progress every 10 seconds.
- A list of recent logs is listed below the current migration progress textarea.
- Clicking a link in the recent logs section will load the content of the log into the textarea.  You can also right click and `Open Link in New Tab` to download the log file.
- There are 4 types of logs in the section:
    - 'vmware_migration_TIMESTAMP.log' - These logs show the details for previous migrations.
    - 'vmware_api.log' (default name) - This log captures the information that VMware returns when the VMs are discovered (on page load).
    - 'cs_request.log' (default name) - This log captures the details of the api calls to Apache CloudStack.  This log is reset on each page load.
    - 'help.txt' - This is a help file to explain the different stages the migration progress goes through.  
\ 


INSTALLATION & SETUP
--------------------

### The Source VMware Environment

No changes should be required in the source VMware environment, but a user is required which has access to modify everything in the source VMware environment.  This is because VMs will be Stopped and then Exported from VMware and then migrated to the new Apache CloudStack environment.

Review the configuration details in the `[VMWARE]` section of the `./settings.conf` config file below.  
\ 

### The Migration Machine

This guide assumes a CentOS environment because it has more gotchas due to having older libraries.  It should work on Ubuntu with less steps.

This tool is run from its own dedicated VM in your environment.  The migration VM handles the orchestration of all of the migration activities.  The VMs are exported from the source VMware environment to a location on the migration machine.  This location is likely going to be an NFS mount because you will need 3 to 4 times as much space as the size of the largest VM to be migrated.  

Once the VM has been exported, if it has multiple disks, then the export is split up into one OVA file per disk.  The first OVA file represents the VM template in Apache CloudStack, and the subsequent OVAs will be data volumes.  A file server is run on the migration VM which exposes the templates and volumes via a URL for Apache CloudStack to be able to download the files.  

Once the files have been uploaded to Apache CloudStack, a new VM will be launched using the template and then the additional data volumes will be attached once the VM is up and running.

The following describes how the Migration VM is configured...  
\ 

**Install EPEL**
``` bash
$ rpm -ivh http://dl.fedoraproject.org/pub/epel/6/x86_64/epel-release-6-8.noarch.rpm
```
\ 

**Install PIP and Git**
``` bash
$ sudo yum install python-pip git
$ sudo yum install python-devel
$ sudo yum install gmp-devel
```
\ 

**Install python dependencies**
``` bash
$ sudo pip install argparse
$ sudo pip install bottle
$ sudo pip install cherrypy
$ sudo pip install netaddr
$ sudo pip install pysphere
$ sudo pip uninstall pycrypto
$ sudo pip install pycrypto
$ sudo pip install cpbmapi
```
\ 

**Get the source code**

To simplify later instructions, it is assumed that the code is pulled into the '~/' directory.  The location of the code is not important since it is run in place and is not installed.

``` bash
$ cd ~/
$ git clone https://github.com/swill/migrate2cs.git
```
\ 

**Install the OVFtool**

This tool is used to export VMs from VMware.

``` bash
$ cd ~/migrate2cs/extras
$ chmod u+x VMware-ovftool-3.5.0-1274719-lin.x86_64.sh
$ ./VMware-ovftool-3.5.0-1274719-lin.x86_64.sh
```

Note that `sudo` may not work.  You my have to login as `root` to make the install work.  

If this does not work, get the latest `ovftool` from: `https://www.vmware.com/support/developer/ovf/`  
\ 

**Setup where the OVA files will be stored**

Here we setup the location where the exported OVA files will be copied to and then served from in order for Apache CloudStack to upload the files.  The migration tool needs file system access to this location to save and modify the OVA files.  It is recommended that you use something like an NFS mount point to ensure you have enough space.  You need 3 to 4 times the amount of space as the largest VM (total of all its disks) you will be migrating.  This documentation assumes that an NFS share is being used and is mounted at `/mnt/share` with a target directory of `ovas` in that share.

``` bash
$ mkdir -p /mnt/share
$ mount -t nfs NFS_IP_OR_HOST:/PATH/TO/NFS/SHARE /mnt/share
$ mkdir -p /mnt/share/ovas
```
\ 

**Setup a file server to serve the OVAs**

In order for Apache CloudStack to access the OVA files, there needs to be a file server exposing the `/mnt/share/ovas` directory.  The file server MUST serve the files on either port `80` or `443` in order for Apache CloudStack to be able to access them.  The type of file server is not important, but in order to simplify the deployment documentation, I have included a file server with the tool.  The following instructions will use the file server I have included to expose the files in the `/mnt/share/ovas` directory.

``` bash
$ cp ~/migrate2cs/extras/file_server.py /mnt/share/ovas
$ cd /mnt/share/ovas
$ nohup python file_server.py -x .out &
```
\ 

**Setup the config file `./settings.conf`**

The `./settings.conf` file uses an INI format and is the main configuration mechanism for the application.

All of the fields that are labeled as OPTIONAL are showing the default values that are being used.

**NOTE:** All the values in the REQUIRED fields are only placeholders so you understand the format.  They must be replaced with your settings.

``` ini
### NOTES: both '#' and ';' are used for comments.  only ';' can be used for inline comments.

[GLOBAL]
### REQUIRED: this is the details for the sensitive data encryption cipher
# cipher_key must have a length of 16, 24 or 36
cipher_key = a916b62309c7a33ec332dc3388554033


[VMWARE]
### REQUIRED: this is the details for the VMware which is being migrated from
endpoint = 10.223.130.53
username = administrator@vsphere.local
password = Passw0rd1!

### OPTIONAL: these are defined in the code, change them as needed
## log_file = ./logs/vmware_api.log
## max_virtual_hardware_version = 9


[CLOUDSTACK]
### REQUIRED: these are the details for the Apache CloudStack install which VMs are being migrated to
host = 10.223.130.192:8080

# these keys are for the 'admin' user so the tool can act on behalf of other users
api_key = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
secret_key = yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy

### OPTIONAL: these are defined in the code, change them as needed
## protocol = http
## uri = /client/api
## async_poll_interval = 5
## logging = True
## log_file = ./logs/cs_request.log


[FILESERVER]
### REQUIRED: where the OVA files will be copied to and then served from for Apache CloudStack to access
host = 10.223.130.146          ; this is the ip of the migration machine
port = 80                      ; this needs to be 80 or 443 for Apache CloudStack to use it
base_uri = /                   ; the file name will be appended to this path in the url
files_path = /mnt/share/ovas   ; this is where the files will get saved to and served from


[WEBSERVER]
### OPTIONAL: will work with the default settings.  this is the migration ui web server.
## debug = False
## port = 8787
```
\ 


UNDER THE HOOD
--------------

### Limitations and special considerations

- The tool fully supports VMs with SCSI controllers.
- The tool only partially supports VMs with IDE root volume controllers.  The VM will import correctly, but it will crash on boot due to a problem locating the root partition.  Manual manipulation is required to complete the migration.
- The tool supports VMs with both single and multiple disks.
    - The additional disks will be uploaded to Apache CloudStack as data volumes and will be attached to the VM after it launches.
- When migrating from a more recent version of VMware to a previous version of VMware, you will need to specify the 'max_virtual_hardware_version' setting to reflect the destination VMware version.  The possible settings and the respective VMware version supported are listed below.  The default setting is '9'...
    - 10 - Supports: ESXi 5.5, Fusion 6.x, Workstation 10.x, Player 6.x
    - 9 - Supports: ESXi 5.1, Fusion 5.x, Workstation 9.x, Player 5.x
    - 8 - Supports: ESXi 5.0, Fusion 4.x, Workstation 8.x, Player 4.x
    - 7 - Supports: ESXi/ESX 4.x, Fusion 3.x, Fusion 2.x, Workstation 7.x, Workstation 6.5.x, Player 3.x, Server 2.x
    - 6 - Supports: Workstation 6.0.x
    - 4 - Supports: ACE 2.x, ESX 3.x, Fusion 1.x, Player 2.x
    - 3 and 4 - Supports: ACE 1.x, Lab Manager 2.x, Player 1.x, Server 1.x, Workstation 5.x, Workstation 4.x
    - 3 - Supports: ESX 2.x, GSX Server 3.x  
\ 

### The migration states

- [no state] - The default migration state is an empty string which means the migration process needs to start from the beginning.
- exported - The VM has been exported and the OVA is ready to be imported.
- imported - The VM has been imported into Apache CloudStack and the upload process has been kicked off.
- launched - A transition state after the VM is launched in Apache CloudStack and before the migration has been cleaned up.
- migrated - The VM has been successfully migrated to Apache CloudStack and is up and running.  
\ 

### Migration state management

- The state of the migration is stored in the `./running.conf` file.
- The `./running.conf` file is a superset of the parameters configured in `./settings.conf` and maintains the current state of all the migrations.
- If the `./running.conf` file is removed, the migration UI will be reset to its defaults plus the contents of the `./settings.conf` file.
- It is NOT recommended to modify the `./running.conf` file unless you really understand what the implications are.
- The `./running.conf` includes all of the configuration specified in the `./settings.conf` file, the defaults specified in code as well as:
    - `vms` - The details for all the discovered VMs and the information stored associated with the VMs during the migration.
    - `cs_objs` - The details for the available Apache CloudStack objects that VMs can be applied to.
    - `vm_order` - The order of the VMs so the order is consistent between reloads.
    - `migrate` - An array of VMs that are currently being migrated.
    - `migrate_error` - A boolean that tracks if the current migration has errors.
    - `migration_timestamp` - The timestamp associated with the last migration.
    - `active_migration` - A boolean to specify if there is a migration currently happening.  
\ 

TROUBLESHOOTING
---------------

Every system is slightly different and may not behave exactly as expected.  Here are some points to be aware of.  
\ 

### Linux

**IP address is not configured in target machine**

This can happen if the source VM was using a `static` IP.  You will need to modify the `eth0` config to make it use DHCP.

*CentOS*
```
$ sudo vim /etc/sysconfig/network-scripts/ifcfg-eth0
    # change
    BOOTPROTO="static"
    # to
    BOOTPROTO="dhcp"
$ sudo ifdown eth0
$ sudo ifup eth0
```
\ 

### Windows

Periodically I have seen Windows boxes come up in a slightly confused state.  Rebooting the VM and selecting `Start Windows Normally` usually solves the problem.  
\ 
