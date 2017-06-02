#!/usr/bin/env python

from ConfigParser import ConfigParser
from pysphere import VIServer
from lib.cloudstack import cs
from lib.cpbm import cpbm
from lib.common import *
from xml.etree import ElementTree as ET
import json
import logging
import os
import pprint
import re
import subprocess
import sys
import time
import urllib
if sys.version_info < (2, 7):
	import lib.legacy_subprocess
	subprocess.check_output = lib.legacy_subprocess.check_output

# setup the conf object and set default values...
conf = ConfigParser()
conf.add_section('VMWARE')
conf.set('VMWARE', 'log_file', './logs/vmware_api.log')
conf.set('VMWARE', 'max_virtual_hardware_version', '9')

# read in config files if they exists
conf.read(['./settings.conf', './running.conf'])

# get and hash the password...
vmware_pass = password_hash('VMWARE', 'password', 'password_hash')

if not conf.has_section('STATE'):
	conf.add_section('STATE') # STATE config section to maintain state of the running process
if not conf.has_option('STATE', 'migrate'):
	conf.set('STATE', 'migrate', '[]') # parsed with: json.loads(conf.get('STATE', 'migrate'))

conf.set('VMWARE', 'migration_log_file', './logs/vmware_migration_%s.log' % (conf.get('STATE', 'migration_timestamp')))
with open('running.conf', 'wb') as f:
	conf.write(f) # update the file to include the changes we have made

# add migration logging
log = logging.getLogger()
log_handler = logging.FileHandler(conf.get('VMWARE', 'migration_log_file'))
log_format = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
log_handler.setFormatter(log_format)
log.addHandler(log_handler) 
log.setLevel(logging.INFO)

conf.set('STATE', 'migrate_error', 'False')

def export_vm(vm_id):
	conf.read(['./running.conf'])
	if not conf.getboolean('STATE', 'migrate_error'):
		vms = json.loads(conf.get('STATE', 'vms'))
		log.info('EXPORTING %s' % (vms[vm_id]['src_name']))
		vms[vm_id]['clean_name'] = re.sub('[^0-9a-zA-Z]+', '-', vms[vm_id]['src_name']).strip('-')
		if len(vms[vm_id]['clean_name']) > 63:
			vms[vm_id]['clean_name'] = vms[vm_id]['clean_name'][:63]

		output = ''
		cmd = 'ovftool %s -tt=OVA -n=%s "vi://%s:%s@%s?moref=vim.VirtualMachine:%s" %s' % (
			'-o --powerOffSource --noSSLVerify --acceptAllEulas --maxVirtualHardwareVersion=%s' % (
				conf.get('VMWARE', 'max_virtual_hardware_version')),
			vms[vm_id]['clean_name'],
			urllib.quote_plus(conf.get('VMWARE', 'username')),
			urllib.quote_plus(vmware_pass),
			conf.get('VMWARE', 'endpoint'),
			vm_id,
			conf.get('FILESERVER', 'files_path')
		)
		try:
			output = subprocess.check_output(cmd, shell=True)
			log.info('OVFtool output:\n%s' % (output))
		except subprocess.CalledProcessError, e:
			log.error('Could not export %s \n%s' % (vms[vm_id]['src_name'], e.output))
			conf.read(['./running.conf'])
			conf.set('STATE', 'migrate_error', 'True')
			conf.set('STATE', 'vms', json.dumps(vms))
			with open('running.conf', 'wb') as f:
				conf.write(f) # update the file to include the changes we have made

		if not conf.getboolean('STATE', 'migrate_error'):
			# we have the resulting OVA file.  process the OVA file...
			if len(vms[vm_id]['src_disks']) > 1:
				log.info('Processing multi disk ova...')
			elif len(vms[vm_id]['src_disks']) == 1:
				log.info('Processing single disk ova...')
			conf.set('STATE', 'vms', json.dumps(vms))
			with open('running.conf', 'wb') as f:
				conf.write(f) # update the file to include the changes we have made
			split_ok = True
			split_ok = split_ova(vm_id)
			if split_ok:
				conf.read(['./running.conf'])
				vms = json.loads(conf.get('STATE', 'vms'))
			if split_ok:
				log.info('Finished exporting %s' % (vms[vm_id]['src_name']))
				vms[vm_id]['state'] = 'exported'
			else:
				log.error('There were problems exporting the disks for %s' % (vms[vm_id]['src_name']))
			conf.set('STATE', 'vms', json.dumps(vms))
			with open('running.conf', 'wb') as f:
				conf.write(f) # update the file to include the changes we have made
	else:
		log.info('An error has occurred.  Skipping the export process...')

def split_ova(vm_id):
	split_ok = True
	conf.read(['./running.conf'])
	vms = json.loads(conf.get('STATE', 'vms'))
	## this script is designed to work with Python 2.5+, so we are not using anything from ElementTree 1.3, only 1.2...
	## this is important in order to support CentOS.

	ns = {}
	ns['ns'] = 'http://schemas.dmtf.org/ovf/envelope/1'
	ns['ovf'] = 'http://schemas.dmtf.org/ovf/envelope/1'
	ns['cim'] = 'http://schemas.dmtf.org/wbem/wscim/1/common'
	ns['rasd'] = 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData'
	ns['vmw'] = 'http://www.vmware.com/schema/ovf'
	ns['vssd'] = 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData'
	ns['xsi'] = 'http://www.w3.org/2001/XMLSchema-instance'

	ET._namespace_map[ns['ovf']] = 'ovf'
	ET._namespace_map[ns['cim']] = 'cim'
	ET._namespace_map[ns['rasd']] = 'rasd'
	ET._namespace_map[ns['vmw']] = 'vmw'
	ET._namespace_map[ns['vssd']] = 'vssd'
	ET._namespace_map[ns['xsi']] = 'xsi'

	DISK_RESOURCE_TYPE = 17

	src_ova_file = '%s.ova' % (vms[vm_id]['clean_name'])
	src_ova_base = vms[vm_id]['clean_name']
	print('\nExtracting %s...' % (src_ova_file))
	cmd = 'cd %s; rm -rf %s; mkdir %s; tar xvf %s -C %s' % (
		conf.get('FILESERVER', 'files_path'), src_ova_base, src_ova_base, src_ova_file, src_ova_base)
	ret = subprocess.call(cmd, shell=True)

	if ret == 0:
		src_ovf_file = None
		for f in os.listdir('%s/%s' % (conf.get('FILESERVER', 'files_path'), src_ova_base)):
			if f.endswith('.ovf'):
				src_ovf_file = '%s/%s/%s' % (conf.get('FILESERVER', 'files_path'), src_ova_base, f)

		if src_ovf_file:
			src_dom = ET.parse(src_ovf_file)
			src_tree = src_dom.getroot()
			log.info('Extracting and evaluating the ova file.  Creating a new ova file for each disk...')

			for index in xrange(len(src_tree.findall('{%(ns)s}DiskSection/{%(ns)s}Disk' % ns))):
				dom = ET.parse(src_ovf_file)
				tree = dom.getroot()
				split_base = None
				items_to_remove = []

				# get the values we care about for this iteration
				disk_el = tree.findall('{%(ns)s}DiskSection/{%(ns)s}Disk' % ns)[index]
				disk_id = disk_el.attrib.get('{%(ovf)s}diskId' % ns, None)
				file_id = disk_el.attrib.get('{%(ovf)s}fileRef' % ns, None)
				file_nm = None
				for f in tree.findall('{%(ns)s}References/{%(ns)s}File' % ns):
					if f.attrib.get('{%(ovf)s}id' % ns, None) == file_id:
						file_nm = f.attrib.get('{%(ovf)s}href' % ns, None)
				split_base = os.path.splitext(file_nm)[0]

				# get the controller type
				controller_id = None
				controller_type = None
				for i in tree.findall('{%(ns)s}VirtualSystem/{%(ns)s}VirtualHardwareSection/{%(ns)s}Item' % ns):
					if int(i.find('{%(rasd)s}ResourceType' % ns).text) == DISK_RESOURCE_TYPE:
						if i.find('{%(rasd)s}HostResource' % ns).text.endswith(disk_id):
							controller_id = i.find('{%(rasd)s}Parent' % ns).text
				for i in tree.findall('{%(ns)s}VirtualSystem/{%(ns)s}VirtualHardwareSection/{%(ns)s}Item' % ns):
					if i.find('{%(rasd)s}InstanceID' % ns).text == controller_id:
						controller_type = i.find('{%(rasd)s}Description' % ns).text

				if 'IDE' in controller_type:
					log.info('Disk %s is using an IDE controller\n' % (split_base))
					log.warning('The IDE controller is not fully supported.  The VM will need to be manually verified to be working after the migration completes.\n')

				# loop through the different elements and remove the elements we don't want
				for d in tree.findall('{%(ns)s}DiskSection/{%(ns)s}Disk' % ns):
					if d.attrib.get('{%(ovf)s}diskId' % ns, None) != disk_id:
						parent = tree.find('{%(ns)s}DiskSection' % ns)
						parent.remove(d)
				for f in tree.findall('{%(ns)s}References/{%(ns)s}File' % ns):
					if f.attrib.get('{%(ovf)s}id' % ns, None) != file_id:
						items_to_remove.append(f.attrib.get('{%(ovf)s}id' % ns))
						parent = tree.find('{%(ns)s}References' % ns)
						parent.remove(f)
				for i in tree.findall('{%(ns)s}VirtualSystem/{%(ns)s}VirtualHardwareSection/{%(ns)s}Item' % ns):
					if int(i.find('{%(rasd)s}ResourceType' % ns).text) == DISK_RESOURCE_TYPE:
						if not i.find('{%(rasd)s}HostResource' % ns).text.endswith(disk_id):
							parent = tree.find('{%(ns)s}VirtualSystem/{%(ns)s}VirtualHardwareSection' % ns)
							parent.remove(i)

				# remove extra Items associated with deleted elements
				for d in tree.findall('{%(ns)s}VirtualSystem/{%(ns)s}VirtualHardwareSection/{%(ns)s}Item' % ns):
					if d.find('{%(rasd)s}HostResource' % ns) != None:
						for item in items_to_remove:
							if d.find('{%(rasd)s}HostResource' % ns).text.endswith(item):
								parent = tree.find('{%(ns)s}VirtualSystem/{%(ns)s}VirtualHardwareSection' % ns)
								parent.remove(d)

				# update elements that require specific values
				for c in tree.findall('{%(ns)s}VirtualSystem/{%(ns)s}VirtualHardwareSection/{%(vmw)s}Config' % ns):
					if c.attrib.get('{%(vmw)s}key' % ns, None) == 'tools.toolsUpgradePolicy':
						c.set('{%(vmw)s}value' % ns, 'manual')
				
				split_ofv_file = '%s/%s/%s.ovf' % (conf.get('FILESERVER', 'files_path'), src_ova_base, split_base)
				with open(split_ofv_file, 'w') as f:
					f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
					dom.write(f, encoding='utf-8')

				## since the '' and 'ovf' namespaces have the same url, we have to keep the 'ovf' on attributes, but not on tags.
				cmd = "perl -pi -e 's,<ovf:,<,g' %s" % (split_ofv_file)
				ret = subprocess.call(cmd, shell=True)
				cmd = "perl -pi -e 's,</ovf:,</,g' %s" % (split_ofv_file)
				ret = subprocess.call(cmd, shell=True)

				## apparently the namespaces need to be exactly as specified and can't be re-saved.  replace the Envelope.  no id passed...
				ns_str = ''
				for k, v in ns.items():
					if k == 'ns':
						ns_str = '%s xmlns="%s"' % (ns_str, v)
					else:
						ns_str = '%s xmlns:%s="%s"' % (ns_str, k, v)
				cmd = "perl -pi -e 's,<Envelope.*>,%s,g' %s" % (
					'<Envelope%s>' % (ns_str),
					split_ofv_file)
				ret = subprocess.call(cmd, shell=True)

				print('\nCreating %s.ova...' % (split_base))
				cmd = 'cd %s/%s; rm -rf ../%s.ova; tar cvf ../%s.ova %s.ovf %s' % (
					conf.get('FILESERVER', 'files_path'), src_ova_base, split_base, split_base, split_base, file_nm)
				ret = subprocess.call(cmd, shell=True)
				if ret == 0:
					log.info('Created %s.ova' % (split_base))
					if len(vms[vm_id]['src_disks']) > index:
						vms[vm_id]['src_disks'][index]['ova'] = '%s.ova' % (split_base)
						vms[vm_id]['src_disks'][index]['url'] = '%s://%s:%s%s%s' % (
							'https' if conf.get('FILESERVER', 'port') == '443' else 'http',
							conf.get('FILESERVER', 'host'),
							conf.get('FILESERVER', 'port'),
							conf.get('FILESERVER', 'base_uri'),
							'%s.ova' % (split_base))
						conf.set('STATE', 'vms', json.dumps(vms))
						with open('running.conf', 'wb') as f:
							conf.write(f) # update the file to include the changes we have made
					else:
						log.error('Could not save the ova to the vms disk due to index out of bound')
						split_ok = False
				else:
					log.error('Failed to create %s.ova' % (split_base))
					split_ok = False
		else:
			log.error('Failed to locate the source ovf file %s/%s/%s.ovf' % (
				conf.get('FILESERVER', 'files_path'), src_ova_base, src_ova_base))
			split_ok = False
		# remove the directory we used to create the new OVA files
		cmd = 'cd %s; rm -rf %s' % (conf.get('FILESERVER', 'files_path'), src_ova_base)
		ret = subprocess.call(cmd, shell=True)
		if ret == 0:
			log.info('Successfully removed temporary disk files')
		else:
			log.warning('Failed to remove temporary disk files.  Consider cleaning up the directory "%s" after the migration.' % (
				conf.get('FILESERVER', 'files_path')))
	else:
		log.error('Failed to extract the ova file %s/%s' % (conf.get('FILESERVER', 'files_path'), src_ova_file))
		split_ok = False
	return split_ok


def import_vm(vm_id):
	# import the vm
	conf.read(['./running.conf'])
	if not conf.getboolean('STATE', 'migrate_error'):
		vms = json.loads(conf.get('STATE', 'vms'))
		log.info('IMPORTING %s' % (vms[vm_id]['src_name']))
		if vms[vm_id]['src_name'] != vms[vm_id]['clean_name']:
			log.info('Renaming VM from %s to %s to comply with CloudPlatform...' % (vms[vm_id]['src_name'], vms[vm_id]['clean_name']))
		imported = False

		# make sure we have a complete config before we start
		if ('cs_zone' in vms[vm_id] and 'cs_domain' in vms[vm_id] and 'cs_account' in vms[vm_id] and 'cs_service_offering' in vms[vm_id]):
			# manage the disks
			if len(vms[vm_id]['src_disks']) > 0:
				# get the possible os type ids
				os_type = ''
				type_search = 'Other (64-bit)'
				if vms[vm_id]['src_os_arch'] == 32:
					type_search = 'Other (32-bit)'
				type_ids = cs.request(dict({'command':'listOsTypes'}))
				if type_ids and 'ostype' in type_ids:
					for os_type_obj in type_ids['ostype']:
						if os_type_obj['description'] == type_search:
							os_type = os_type_obj['id']
							break

				# register the first disk as a template since it is the root disk
				root_name = os.path.splitext(vms[vm_id]['src_disks'][0]['ova'])[0]
				log.info('Creating template for root volume %s...' % (root_name))
				template = cs.request(dict({
					'command':'registerTemplate',
					'name':root_name,
					'displaytext':root_name,
					'format':'OVA',
					'hypervisor':'VMware',
					'ostypeid':os_type,
					'url':vms[vm_id]['src_disks'][0]['url'],
					'zoneid':vms[vm_id]['cs_zone'],
					'domainid':vms[vm_id]['cs_domain'],
					'account':vms[vm_id]['cs_account'],
					'details[0].nicAdapter':'Vmxnet3'
					#'details[0].rootDiskController':'scsi'
				}))
				if template:
					log.info('Template %s created' % (template['template'][0]['id']))
					vms[vm_id]['cs_template_id'] = template['template'][0]['id']
					imported = True
				else:
					log.error('Failed to create template.  Check the "%s" log for details.' % (conf.get('CLOUDSTACK', 'log_file')))
					conf.read(['./running.conf'])
					conf.set('STATE', 'migrate_error', 'True')
					conf.set('STATE', 'vms', json.dumps(vms))
					with open('running.conf', 'wb') as f:
						conf.write(f) # update the file to include the changes we have made

				# check if there are data disks
				if len(vms[vm_id]['src_disks']) > 1:
					# upload the remaining disks as volumes
					vms[vm_id]['cs_volumes'] = []
					for i,v in enumerate(vms[vm_id]['src_disks'][1:]):
						index = i+1
						imported = False # reset because we have more to do...
						disk_name = os.path.splitext(vms[vm_id]['src_disks'][index]['ova'])[0]
						log.info('Uploading data volume %s...' % (disk_name))
						volume = cs.request(dict({
							'command':'uploadVolume',
							'name':disk_name,
							'format':'OVA',
							'url':vms[vm_id]['src_disks'][index]['url'],
							'zoneid':vms[vm_id]['cs_zone'],
							'domainid':vms[vm_id]['cs_domain'],
							'account':vms[vm_id]['cs_account']
						}))
						if volume and 'jobresult' in volume and 'volume' in volume['jobresult']:
							volume_id = volume['jobresult']['volume']['id']
							log.info('Volume %s uploaded' % (volume_id))
							vms[vm_id]['cs_volumes'].append(volume_id)
							imported = True
						else:
							log.error('Failed to upload the volume.  Check the "%s" log for details.' % (conf.get('CLOUDSTACK', 'log_file')))
							if volume and 'jobresult' in volume and 'errortext' in volume['jobresult']:
								log.error('ERROR: %s' % (volume['jobresult']['errortext']))
							conf.read(['./running.conf'])
							conf.set('STATE', 'migrate_error', 'True')
							conf.set('STATE', 'vms', json.dumps(vms))
							with open('running.conf', 'wb') as f:
								conf.write(f) # update the file to include the changes we have made
		else:
			log.error('We are missing CCP data for %s' % (vms[vm_id]['src_name']))
			conf.read(['./running.conf'])
			conf.set('STATE', 'migrate_error', 'True')
			conf.set('STATE', 'vms', json.dumps(vms))
			with open('running.conf', 'wb') as f:
				conf.write(f) # update the file to include the changes we have made

		if imported:
			### Update the running.conf file
			log.info('Finished importing %s' % (vms[vm_id]['clean_name']))
			vms[vm_id]['state'] = 'imported'
			conf.set('STATE', 'vms', json.dumps(vms))
			with open('running.conf', 'wb') as f:
				conf.write(f) # update the file to include the changes we have made
		else:
			log.warning('Fail to import %s' % (vms[vm_id]['clean_name']))
	else:
		log.info('An error has occurred.  Skipping the import process...')

def launch_vm(vm_id):
	# launch the new vm
	conf.read(['./running.conf'])
	if not conf.getboolean('STATE', 'migrate_error'):
		vms = json.loads(conf.get('STATE', 'vms'))
		log.info('LAUNCHING %s' % (vms[vm_id]['clean_name']))

		poll = 1
		has_error = False
		while not has_error and vms[vm_id]['state'] != 'launched':
			# check if the template has finished downloading...
			template = cs.request(dict({
				'command':'listTemplates', 
				'listall':'true', 
				'templatefilter':'self', 
				'id':vms[vm_id]['cs_template_id']
			}))
			if template and 'template' in template and len(template['template']) > 0:
				if template['template'][0]['isready']: # template is ready
					volumes_ready = True
					if 'cs_volumes' in vms[vm_id] and len(vms[vm_id]['cs_volumes']) > 0: # check if volumes are ready
						volumes_ready = False
						volume_bools = [False for i in range(len(vms[vm_id]['cs_volumes']))] # boolean for each volume
						for i, volume_id in enumerate(vms[vm_id]['cs_volumes']):
							volume = cs.request(dict({
								'command':'listVolumes', 
								'listall':'true', 
								'id':volume_id
							}))
							if volume and 'volume' in volume and len(volume['volume']) > 0:
								# check the state of the volume
								if volume['volume'][0]['state'] != 'Uploaded' and volume['volume'][0]['state'] != 'Ready':
									log.info('%s: %s is waiting for volume %s, current state: %s' % 
										(poll, vms[vm_id]['clean_name'], volume['volume'][0]['name'], volume['volume'][0]['state']))
									volume_bools[i] = False
								else:
									volume_bools[i] = True
							else:
								log.error('Failed to locate volume %s' % (volume_id))
								has_error = True
								conf.read(['./running.conf'])
								conf.set('STATE', 'migrate_error', 'True')
								conf.set('STATE', 'vms', json.dumps(vms))
								with open('running.conf', 'wb') as f:
									conf.write(f) # update the file to include the changes we have made
						volumes_ready = all(volume_bools) # True if all volume booleans are True

					# everything should be ready for this VM to be started, go ahead...
					if volumes_ready:
						log.info('%s: %s is ready to launch' % (poll, vms[vm_id]['clean_name']))
						log.info('Launching VM %s (this will take a while)...' % (vms[vm_id]['clean_name']))
						# create a VM instance using the template
						if 'cpbm_bundle' in vms[vm_id]:
							# create the VM using the CPBM Subscription API and subscribe to the specified bundle.
							sub_data = {
								'hostName':vms[vm_id]['clean_name'],
								'displayName':vms[vm_id]['clean_name'],
								'serviceOfferingUuid':vms[vm_id]['cs_service_offering'],
								'templateUuid':vms[vm_id]['cs_template_id'],
								'zoneUuid':vms[vm_id]['cs_zone']
							}
							if 'cs_network' in vms[vm_id] and vms[vm_id]['cs_network'] != '': # pass in a network if it is available
								sub_data['networkIds'] = vms[vm_id]['cs_network']
								if 'cs_ip_address' in vms[vm_id] and vms[vm_id]['cs_ip_address'] != '': # pass in the IP if specified
									sub_data['ipAddress'] = vms[vm_id]['cs_ip_address']
							sub = cpbm.request('/accounts/%s/subscriptions' % (vms[vm_id]['cpbm_account']), {
								'productbundleid':vms[vm_id]['cpbm_bundle'],
								'provision':True,
								'configurationdata':json.dumps(sub_data)
							}, method='POST')

							print("\nSubscription for %s" % (vms[vm_id]['clean_name']))
							pprint.pprint(sub)
							polls_remaining = 6 # the number of polls total to wait for a VM to show up (60 seconds)
							found_vm = False # flag to let us split the logic based on if the vm is found
							while polls_remaining > 0 and not has_error and vms[vm_id]['state'] != 'launched':
								# search for the newly created VM because the CPBM API does not return a reference to it.
								cs_vm = cs.request({
									'command':'listVirtualMachines',
									'name':vms[vm_id]['clean_name'],
									'domainid':vms[vm_id]['cs_domain'],
									'account':vms[vm_id]['cs_account']
								})
								if cs_vm and 'virtualmachine' in cs_vm and len(cs_vm['virtualmachine']) > 0:
									if not found_vm: # first pass through checking a found vm
										found_vm = True
										polls_remaining = 360 # give the VM 60 minutes to start before assume we have a problem
										log.info('VM %s created, waiting for it to launch' % (vms[vm_id]['clean_name']))

									if 'state' in cs_vm['virtualmachine'][0] and cs_vm['virtualmachine'][0]['state'] == 'Running':
										log.info('VM %s launched' % (vms[vm_id]['clean_name']))
										time.sleep(10) # give it a second to breath to make sure the VM is ready for attaching volumes

										# attach the data volumes to it if there are data volumes
										if 'cs_volumes' in vms[vm_id] and len(vms[vm_id]['cs_volumes']) > 0:
											for volume_id in vms[vm_id]['cs_volumes']:
												log.info('Attaching volume %s...' % (volume_id))
												attach = cs.request(dict({
													'command':'attachVolume',
													'id':volume_id,
													'virtualmachineid':cs_vm['virtualmachine'][0]['id']}))
												if attach and 'jobstatus' in attach and attach['jobstatus'] == 1:
													log.info('Successfully attached volume %s' % (volume_id))
												else:
													log.error('Failed to attach volume %s' % (volume_id))
													if attach and 'jobresult' in attach and 'errortext' in attach['jobresult']:
														log.error('ERROR: %s' % (attach['jobresult']['errortext']))
													has_error = True
													conf.read(['./running.conf'])
													conf.set('STATE', 'migrate_error', 'True')
													conf.set('STATE', 'vms', json.dumps(vms))
													with open('running.conf', 'wb') as f:
														conf.write(f) # update the file to include the changes we have made
											if not has_error:
												log.info('Rebooting the VM to make the attached volumes visible...')
												reboot = cs.request(dict({
													'command':'rebootVirtualMachine', 
													'id':cs_vm['virtualmachine'][0]['id']}))
												if reboot and 'jobstatus' in reboot and reboot['jobstatus'] == 1:
													log.info('VM rebooted')
												else:
													log.error('VM did not reboot.  Check the VM to make sure it came up correctly.')
													if reboot and 'jobresult' in reboot and 'errortext' in reboot['jobresult']:
														log.error('ERROR: %s' % (reboot['jobresult']['errortext']))
										if not has_error:
											### Update the running.conf file
											conf.read(['./running.conf']) # make sure we have everything from this file already
											vms[vm_id]['cs_vm_id'] = cs_vm['virtualmachine'][0]['id']
											vms[vm_id]['state'] = 'launched'
											conf.set('STATE', 'vms', json.dumps(vms))
											with open('running.conf', 'wb') as f:
												conf.write(f) # update the file to include the changes we have made
									else:
										polls_remaining -= 1
										if polls_remaining == 0:
											log.error('Failed to start VM %s in the allotted time' % (vms[vm_id]['clean_name']))
											has_error = True
											conf.read(['./running.conf'])
											conf.set('STATE', 'migrate_error', 'True')
											conf.set('STATE', 'vms', json.dumps(vms))
											with open('running.conf', 'wb') as f:
												conf.write(f) # update the file to include the changes we have made
								else:
									polls_remaining -= 1
									if polls_remaining == 0:
										log.error('Failed to find VM %s in the allotted time' % (vms[vm_id]['clean_name']))
										has_error = True
										conf.read(['./running.conf'])
										conf.set('STATE', 'migrate_error', 'True')
										conf.set('STATE', 'vms', json.dumps(vms))
										with open('running.conf', 'wb') as f:
											conf.write(f) # update the file to include the changes we have made

								if vms[vm_id]['state'] != 'launched' and not has_error:
									log.info('... polling ...')
									time.sleep(10)
						else:
							# create the VM using the CCP API.
							cmd = dict({
								'command':'deployVirtualMachine',
								'name':vms[vm_id]['clean_name'],
								'displayname':vms[vm_id]['clean_name'],
								'templateid':vms[vm_id]['cs_template_id'],
								'serviceofferingid':vms[vm_id]['cs_service_offering'],
								'zoneid':vms[vm_id]['cs_zone'],
								'domainid':vms[vm_id]['cs_domain'],
								'account':vms[vm_id]['cs_account']
							})
							if 'cs_network' in vms[vm_id] and vms[vm_id]['cs_network'] != '': # pass in a network if it is available
								cmd['networkids'] = vms[vm_id]['cs_network']
								if 'cs_ip_address' in vms[vm_id] and vms[vm_id]['cs_ip_address'] != '': # pass in the IP if specified
									cmd['ipaddress'] = vms[vm_id]['cs_ip_address']
							cs_vm = cs.request(cmd) # launch the VM
							if cs_vm and 'jobresult' in cs_vm and 'virtualmachine' in cs_vm['jobresult']:
								log.info('VM %s launched' % (vms[vm_id]['clean_name']))

								# attach the data volumes to it if there are data volumes
								if 'cs_volumes' in vms[vm_id] and len(vms[vm_id]['cs_volumes']) > 0:
									for volume_id in vms[vm_id]['cs_volumes']:
										log.info('Attaching volume %s...' % (volume_id))
										attach = cs.request(dict({
											'command':'attachVolume',
											'id':volume_id,
											'virtualmachineid':cs_vm['jobresult']['virtualmachine']['id']}))
										if attach and 'jobstatus' in attach and attach['jobstatus'] == 1:
											log.info('Successfully attached volume %s' % (volume_id))
										else:
											log.error('Failed to attach volume %s' % (volume_id))
											if attach and 'jobresult' in attach and 'errortext' in attach['jobresult']:
												log.error('ERROR: %s' % (attach['jobresult']['errortext']))
											has_error = True
											conf.read(['./running.conf'])
											conf.set('STATE', 'migrate_error', 'True')
											conf.set('STATE', 'vms', json.dumps(vms))
											with open('running.conf', 'wb') as f:
												conf.write(f) # update the file to include the changes we have made
									if not has_error:
										log.info('Rebooting the VM to make the attached volumes visible...')
										reboot = cs.request(dict({
											'command':'rebootVirtualMachine', 
											'id':cs_vm['jobresult']['virtualmachine']['id']}))
										if reboot and 'jobstatus' in reboot and reboot['jobstatus'] == 1:
											log.info('VM rebooted')
										else:
											log.error('VM did not reboot.  Check the VM to make sure it came up correctly.')
											if reboot and 'jobresult' in reboot and 'errortext' in reboot['jobresult']:
												log.error('ERROR: %s' % (reboot['jobresult']['errortext']))
								if not has_error:
									### Update the running.conf file
									conf.read(['./running.conf']) # make sure we have everything from this file already
									vms[vm_id]['cs_vm_id'] = cs_vm['jobresult']['virtualmachine']['id']
									vms[vm_id]['state'] = 'launched'
									conf.set('STATE', 'vms', json.dumps(vms))
									with open('running.conf', 'wb') as f:
										conf.write(f) # update the file to include the changes we have made
							else:
								log.error('%s failed to start!  Check the "cs_request.log" for details...' % (vms[vm_id]['clean_name']))
								if cs_vm and 'jobresult' in cs_vm and 'errortext' in cs_vm['jobresult']:
									log.error('ERROR: %s' % (cs_vm['jobresult']['errortext']))
								has_error = True
								conf.read(['./running.conf'])
								conf.set('STATE', 'migrate_error', 'True')
								conf.set('STATE', 'vms', json.dumps(vms))
								with open('running.conf', 'wb') as f:
									conf.write(f) # update the file to include the changes we have made
					else:
						log.info('%s: %s is waiting for volumes...'% (poll, vms[vm_id]['clean_name']))
				else:
					if 'status' in template['template'][0]:
						log.info('%s: %s is waiting for template, current state: %s'% (poll, vms[vm_id]['clean_name'], template['template'][0]['status']))
					else:
						log.info('%s: %s is waiting for template...'% (poll, vms[vm_id]['clean_name']))
					
			if vms[vm_id]['state'] != 'launched' and not has_error:
				log.info('... polling ...')
				poll = poll + 1
				time.sleep(10)
		if not has_error: # complete the migration...
			conf.read(['./running.conf'])
			vms = json.loads(conf.get('STATE', 'vms'))

			# clean up ova files
			cmd = 'cd %s; rm -f %s.ova %s-disk*' % (conf.get('FILESERVER', 'files_path'), vms[vm_id]['clean_name'], vms[vm_id]['clean_name'])
			ret = subprocess.call(cmd, shell=True)
			if ret == 0:
				log.info('Successfully removed the imported OVA files from the file server')
			else:
				log.warning('Failed to remove the imported OVA files.  Consider cleaning up the directory "%s" after the migration.' % (
					conf.get('FILESERVER', 'files_path')))

			# save the updated state
			vms[vm_id]['state'] = 'migrated'
			conf.set('STATE', 'vms', json.dumps(vms))
			migrate = json.loads(conf.get('STATE', 'migrate'))
			migrate.remove(vm_id)
			conf.set('STATE', 'migrate', json.dumps(migrate))
			with open('running.conf', 'wb') as f:
				conf.write(f) # update the file to include the changes we have made
			log.info('SUCCESSFULLY MIGRATED %s to %s\n\n' % (vms[vm_id]['src_name'], vms[vm_id]['clean_name']))
	else:
		log.info('An error has occurred.  Skipping the launch process...')

# run the actual migration
def do_migration():
	conf.read(['./running.conf'])
	vms = json.loads(conf.get('STATE', 'vms'))
	migrate = json.loads(conf.get('STATE', 'migrate'))
	for vm_id in migrate[:]: # makes a copy of the list so we can delete from the original
		if conf.getboolean('STATE', 'migrate_error'):
			break
		state = vms[vm_id]['state']
		if state == '' or state == 'migrated':
			export_vm(vm_id)
			import_vm(vm_id)
			launch_vm(vm_id)
		elif state == 'exported':
			import_vm(vm_id)
			launch_vm(vm_id)
		elif state == 'imported':
			launch_vm(vm_id)
		elif state == 'launched':
			conf.read(['./running.conf'])
			vms = json.loads(conf.get('STATE', 'vms'))
			vms[vm_id]['state'] = 'migrated'
			conf.set('STATE', 'vms', json.dumps(vms))
			migrate.remove(vm_id)
			conf.set('STATE', 'migrate', json.dumps(migrate))
			with open('running.conf', 'wb') as f:
				conf.write(f) # update the file to include the changes we have made


if __name__ == "__main__":
	do_migration()
	conf.read(['./running.conf'])
	if conf.getboolean('STATE', 'migrate_error'):
		log.info('Finished with ERRORS!!!\n')
	else:
		log.info('ALL FINISHED!!!\n')
	log.info('~~~ ~~~ ~~~ ~~~')
	conf.set('STATE', 'active_migration', 'False')
	conf.set('STATE', 'migrate_error', 'False')
	with open('running.conf', 'wb') as f:
		conf.write(f) # update the file to include the changes we have made

