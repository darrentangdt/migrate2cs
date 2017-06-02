from ConfigParser import ConfigParser
import bottle
import json
from lib.cloudstack import CloudStack, cs
from lib.cpbm import cpbm
import netaddr
import os
import pprint
import subprocess

conf = ConfigParser()
# read in config files if they exist
conf.read(['./settings.conf', './running.conf'])

if not conf.has_section('STATE'):
	conf.add_section('STATE') # STATE config section to maintain state of the running process

###  FUNCTIONS  ###

def cs_discover_accounts():
	conf.read(['./running.conf'])
	if conf.has_option('STATE', 'cs_objs'):
		obj = json.loads(conf.get('STATE', 'cs_objs'))
	else:
		obj = {}

	accounts = cs.request(dict({'command':'listAccounts', 'listAll':True}))
	cpbm_accounts = None
	if cpbm:
		cpbm_accounts = cpbm.request('/accounts', {'state':'ACTIVE'})
	if accounts and 'account' in accounts:
		if 'accounts' not in obj:
			obj['accounts'] = {}
		for account in accounts['account']:
			cpbm_account_name = ''
			if cpbm_accounts and 'accounts' in cpbm_accounts:
				for cpbm_account in cpbm_accounts['accounts']:
					if cpbm_account['accountId'] == account['domain']:
						cpbm_account_name = cpbm_account['name']
						break
			if cpbm_account_name != '':
				display = '%s/%s/%s' % (cpbm_account_name, account['domain'], account['name'])
			else:
				display = '%s/%s' % (account['domain'], account['name'])
			if display not in obj['accounts']:
				obj['accounts'][display] = {'display':display, 'id':account['id'], 'account':account['name'], 'domain':account['domainid']}
				if cpbm_account_name != '':
					obj['accounts'][display]['cpbm_name'] = cpbm_account_name
			#pprint.pprint(account)
			#print("")
	else:
		bottle.abort(500, "Could not get the CloudPlatform accounts.")

	### Update the running.conf file
	conf.set('STATE', 'cs_objs', json.dumps(obj))
	with open('running.conf', 'wb') as f:
		conf.write(f) # update the file to include the changes we have made
	return obj


def cs_discover_account_resources(account):
	conf.read(['./running.conf'])
	if conf.has_option('STATE', 'cs_objs'):
		obj = json.loads(conf.get('STATE', 'cs_objs'))
	else:
		obj = {}

	if 'accounts' not in obj:
		obj['accounts'] = {}
	if account['display'] not in obj['accounts']:
		obj['accounts'][account['display']] = account

	cpbm_account = None
	users = cs.request(dict({
		'command':'listUsers', 
		'account':account['account'], 
		'domainid':account['domain'], 
		'state':'enabled',
		'listAll':True}))
	if users and 'user' in users and len(users['user']) > 0:
		user_session = None
		for user in users['user']:
			# loop through to see if any of the existing users in this account have api credentials
			if 'apikey' in user and 'secretkey' in user:
				user_session = CloudStack(
					protocol=conf.get('CLOUDSTACK', 'protocol'), 
					host=conf.get('CLOUDSTACK', 'host'), 
					uri=conf.get('CLOUDSTACK', 'uri'), 
					api_key=user['apikey'], 
					secret_key=user['secretkey'], 
					logging=conf.getboolean('CLOUDSTACK', 'logging'), 
					async_poll_interval=conf.getint('CLOUDSTACK', 'async_poll_interval'))
				break
		if not user_session:
			# add keys to the first user and use them...
			keys = cs.request(dict({'command':'registerUserKeys', 'id':users['user'][0]['id']}))
			if keys and 'userkeys' in keys:
				user_session = CloudStack(
					protocol=conf.get('CLOUDSTACK', 'protocol'), 
					host=conf.get('CLOUDSTACK', 'host'), 
					uri=conf.get('CLOUDSTACK', 'uri'), 
					api_key=keys['userkeys']['apikey'], 
					secret_key=keys['userkeys']['secretkey'], 
					logging=conf.getboolean('CLOUDSTACK', 'logging'), 
					async_poll_interval=conf.getint('CLOUDSTACK', 'async_poll_interval'))

		if user_session:
			if cpbm:
				accounts = cpbm.request('/accounts', {
					'state':'ACTIVE',
					'accountid':users['user'][0]['domain']
				})
				if accounts and 'accounts' in accounts and len(accounts['accounts']) > 0:
					cpbm_account = accounts['accounts'][0]

			zones = user_session.request(dict({'command':'listZones', 'available':'true'}))
			if zones and 'zone' in zones:
				obj['accounts'][account['display']]['zones'] = {}
				for zone in zones['zone']:
					display = zone['name']
					obj['accounts'][account['display']]['zones'][zone['id']] = {'display':display, 'network':zone['networktype'].strip().lower()}
					#pprint.pprint(zone)
					#print("")

			networks = user_session.request(dict({'command':'listNetworks', 'listAll':True}))
			if networks and 'network' in networks:
				obj['accounts'][account['display']]['networks'] = {}
				for network in networks['network']:
					display = '%s - %s' % (network['name'], network['cidr'] if 'cidr' in network else 'shared')
					obj['accounts'][account['display']]['networks'][network['id']] = {'display':display, 'zone':network['zoneid']}
					#pprint.pprint(network)
					#print("")

			offerings = user_session.request(dict({'command':'listServiceOfferings', 'issystem':'false'}))
			if offerings and 'serviceoffering' in offerings:
				catalog = None
				if cpbm and cpbm_account:
					catalog = cpbm.request('/accounts/%s/catalog' % (cpbm_account['uuid']), {
					  'expand':'productRevisions,productBundleRevisions'
					})

				obj['accounts'][account['display']]['offerings'] = {}
				for offering in offerings['serviceoffering']:
					display = '%s - %sx%sMhz, %sM' % (offering['name'], offering['cpunumber'], offering['cpuspeed'], offering['memory'])
					obj['accounts'][account['display']]['offerings'][offering['id']] = {'display':display}
					#pprint.pprint(offering)
					#print("")
					if (catalog and 'catalog' in catalog and 'productBundleRevisions' in catalog['catalog'] and 
							len(catalog['catalog']['productBundleRevisions']) > 0):
						bundles = []
						for bundle in catalog['catalog']['productBundleRevisions']:
							if 'provisioningConstraints' in bundle and len(bundle['provisioningConstraints']) > 0:
								for component in bundle['provisioningConstraints']:
									if ('componentName' in component and component['componentName'] == 'serviceOfferingUuid' and 
											component['value'] == offering['id'] and 'association' in component and
											component['association'] == 'INCLUDES'):
										bundles.append({
											'id':bundle['productBundle']['id'],
											'name':bundle['productBundle']['name'],
											'account':cpbm_account['uuid']
										})
						if len(bundles) > 0:
							obj['accounts'][account['display']]['offerings'][offering['id']]['bundles'] = bundles

	### Update the running.conf file
	conf.set('STATE', 'cs_objs', json.dumps(obj))
	with open('running.conf', 'wb') as f:
		conf.write(f) # update the file to include the changes we have made
	return obj


def get_log_list():
	""" Outputs a link for each file in the logs directory. """
	output = '<h2>Recent Logs</h2><div style="font-family:monospace; padding:5px;">'
	file_list = os.listdir('./logs')
	file_list.sort(reverse=True)
	for file_name in file_list:
		if os.path.isfile('./logs/'+file_name) and '.md' not in file_name:
			output = '%s<a href="/log/%s">%s</a><br />' % (output, file_name, file_name)
	return output+'</div>'


###  COMMON BOTTLE ROUTES  ###

# get resources associated with an account
@bottle.route('/discover/account', method='POST')
def discover_account():
	account = None
	if bottle.request.params.account:
		account = json.loads(bottle.request.params.account)
	if account:
		bottle.response.content_type = 'application/json'
		resources = cs_discover_account_resources(account)
		return json.dumps(resources)
	else:
		return bottle.abort(500, 'Account was not defined correctly.')


# save the 'vms' object from the client to the running.conf
@bottle.route('/ips/get/<network_id>')
def get_ips(network_id):
	vms = cs.request({
		'command':'listVirtualMachines',
		'networkid':network_id
	})
	used_ips = []
	block_ips = []
	# loop through to get the used guest IPs in this network
	if vms and 'virtualmachine' in vms:
		for vm in vms['virtualmachine']:
			nics = cs.request({
				'command':'listNics',
				'virtualmachineid':vm['id'],
				'networkid':network_id
			})
			if nics and 'nic' in nics:
				for nic in nics['nic']:
					used_ips.append(nic['ipaddress'])
					if 'secondaryip' in nic: # get the used secondary IPs as well
						for secip in nic['secondaryip']:
							used_ips.append(secip['ipaddress'])
	net = cs.request({
		'command':'listNetworks',
		'id':network_id
	})
	if net and 'network' in net and len(net['network']) > 0:
		used_ips.append(net['network'][0]['gateway'])
		block_ips = [str(ip) for ip in list(netaddr.IPNetwork(net['network'][0]['cidr']))] # get all possible ips in this cidr
		used_ips.append(block_ips[0]) # Remove the Subnet ID for this range
		used_ips.append(block_ips[-1]) # Remove the Broadcast IP for this range
	return json.dumps([ip for ip in block_ips if ip not in used_ips])


# save the 'vms' object from the client to the running.conf
@bottle.route('/vms/save', method='POST')
def save_vms():
	if bottle.request.params.vms:
		conf.read(['./running.conf'])
		conf.set('STATE', 'vms', bottle.request.params.vms)
		with open('running.conf', 'wb') as f:
			conf.write(f) # update the file to include the changes we have made
		return 'ok'
	else:
		return bottle.abort(500, 'Unable to save the VMs on the server.')


# pull the vms from the running config and refresh the UI
@bottle.route('/vms/refresh')
def refresh_vms():
	conf.read(['./running.conf'])
	vms = json.loads(conf.get('STATE', 'vms'))
	return json.dumps(vms)


# grab the logs to update in the UI
@bottle.route('/logs/refresh')
def refresh_logs():
	return get_log_list()


# serve log files
@bottle.route('/log/<filepath:path>')
def serve_log(filepath):
	""" Download the requested log file. """
	bottle.response.set_header("Content-Type", "application/octet-stream")
	bottle.response.set_header("Content-Disposition", "attachment; filename=\""+filepath+"\";" )
	bottle.response.set_header("Content-Transfer-Encoding", "binary")
	return bottle.static_file(filepath, root='./logs/', download=True)


# serve a favicon.ico so the pages do not return a 404 for the /favicon.ico path in the browser.
@bottle.route('/favicon.ico')
def favicon():
	return bottle.static_file('favicon.png', root='./views/images/')

# routing for static files on the webserver
@bottle.route('/static/<filepath:path>')
def server_static(filepath):
	return bottle.static_file(filepath, root='./')


