#!/usr/bin/env python

# Author: Will Stevens

from ConfigParser import ConfigParser
from lib.cloudstack import cs
import os
import pprint

conf = ConfigParser()
# read in config files if they exist
conf.read(['./settings.conf', './running.conf'])
  
###########################################################
### EXECUTED WHEN THE FILE IS RUN FROM THE COMMAND LINE ###
###########################################################
if __name__ == "__main__":
	# comment out the following line to keep a history of the requests over multiple runs (cloudstack requests log will get large).
	open(conf.get('CLOUDSTACK', 'log_file'), 'w').close() # cleans the cloudstack requests log before execution so it only includes this run.

	zones = cs.request(dict({'command':'listZones'}))
	if zones and 'zone' in zones:
		print('\nZONES:\n------')
		for zone in zones['zone']:
			print('=> %s <=' % (zone['name']))
			print('"cs_zone":"%s",' % (zone['id']))
			print("")

	accounts = cs.request(dict({'command':'listAccounts', 'listAll':True}))
	if accounts and 'account' in accounts:
		print('\nACCOUNTS:\n---------')
		for account in accounts['account']:
			print('=> %s/%s <=' % (account['domain'], account['name']))
			print('"cs_account":"%s",' % (account['name']))
			print('"cs_domain":"%s",' % (account['domainid']))
			print("")

	networks = cs.request(dict({'command':'listNetworks', 'listAll':True}))
	if networks and 'network' in networks:
		print('\nNETWORKS:\n---------')
		for network in networks['network']:
			print('=> %s - %s <=' % (network['name'], network['cidr'] if 'cidr' in network else 'shared'))
			print('"cs_network":"%s",' % (network['id']))
			print("")

	offerings = cs.request(dict({'command':'listServiceOfferings'}))
	if offerings and 'serviceoffering' in offerings:
		print('\nSERVICE OFFERINGS:\n------------------')
		for offering in offerings['serviceoffering']:
			print('=> %s - %sx%sMhz, %sM <=' % (offering['name'], offering['cpunumber'], offering['cpuspeed'], offering['memory']))
			print('"cs_service_offering":"%s",' % (offering['id']))
			print("")


	### clean up the running.conf file...
	#os.remove('./running.conf')
    
