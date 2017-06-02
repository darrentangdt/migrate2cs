#!/usr/bin/env python

# Author: Will Stevens - wstevens@cloudops.com

from ConfigParser import ConfigParser
from lib.common import *
import urllib
import urllib2
import hmac
import hashlib
import base64
import json
import pprint
import time
import os
import sys

# setup the conf object and set default values...
conf = ConfigParser()
conf.add_section('CLOUDSTACK')
conf.set('CLOUDSTACK', 'protocol', 'http')
conf.set('CLOUDSTACK', 'host', '127.0.0.1:8080')
conf.set('CLOUDSTACK', 'uri', '/client/api')
conf.set('CLOUDSTACK', 'async_poll_interval', '10')
conf.set('CLOUDSTACK', 'logging', 'True')
conf.set('CLOUDSTACK', 'log_file', './logs/cs_request.log')

# read in config if it exists
conf.read("./settings.conf")

# get and hash the password(s)...
cs_secret_key = password_hash('CLOUDSTACK', 'secret_key', 'secret_key_hash')

# require an 'api_key' and a 'secret_key' to use this lib
if not conf.has_option('CLOUDSTACK', 'api_key'):
	sys.exit("Config required in settings.conf: [CLOUDSTACK] -> api_key")
if not cs_secret_key:
	sys.exit("Config required in settings.conf: [CLOUDSTACK] -> secret_key")


class CloudStack(object):
	"""
	Login and run queries against the Cloudstack API.
	Example Usage: 
	api = CloudStack(api_key='api_key', secret_key='secret_key'))
	accounts = api.request(dict({'command':'listAccounts'}))
	"""

	def __init__(self, protocol='http', host='127.0.0.1:8080', uri='/client/api', api_key=None, secret_key=None, logging=True, async_poll_interval=5):        
		self.protocol = protocol
		self.host = host
		self.uri = uri
		self.api_key = api_key
		self.secret_key = secret_key
		self.errors = []
		self.logging = logging
		self.async_poll_interval = async_poll_interval # seconds
		
	def request(self, params, poll=1):
		"""Builds a query from params and return a json object of the result or None"""
		self.errors = [] # reset errors so it only prints with its associated call...
		if self.api_key and self.secret_key:
			# add the default and dynamic params
			params['response'] = 'json'
			params['apiKey'] = self.api_key

			# build the query string
			query_params = map(lambda (k,v):k+"="+urllib.quote(str(v)).replace('/', '%2F'), params.items())
			query_string = "&".join(query_params)

			# build signature
			query_params.sort()
			signature_string = "&".join(query_params).lower()
			signature = urllib.quote(base64.b64encode(hmac.new(self.secret_key, signature_string, hashlib.sha1).digest()))

			# final query string...
			url = self.protocol+"://"+self.host+self.uri+"?"+query_string+"&signature="+signature

			output = None
			has_error = False
			try:
				output = json.loads(urllib2.urlopen(url).read())
			except urllib2.HTTPError, e:
				self.errors.append("HTTPError: "+str(e.read()))
				has_error = True
			except urllib2.URLError, e:
				self.errors.append("URLError: "+str(e.reason))
				has_error = True
				
			#pprint.pprint(output) # this will print in the terminal the response without trying to isolate the response data
			if output:
				output = output[(params['command']).lower()+'response']
			#pprint.pprint(output) # this will print in the terminal the same thing as in the cloudstack log file

			# log the request + response data to a log file
			if self.logging:
				with open(conf.get('CLOUDSTACK', 'log_file'), 'a') as f:
					f.write('request:\n')
					f.write(url)
					f.write('\n\n')
					f.write('response:\n')
					if not has_error:
						pprint.pprint(output, f, 2)
					else:
						f.write(repr(self.errors))
					f.write('\n\n\n\n')

			# if the request was an async call, then poll for the result...
			if output and 'jobid' in output.keys() and \
					('jobstatus' not in output.keys() or ('jobstatus' in output.keys() and output['jobstatus'] == 0)):
				#print('%s: polling...' % (poll))
				time.sleep(self.async_poll_interval)
				output = self.request(dict({'command':'queryAsyncJobResult', 'jobId':output['jobid']}), poll+1)

			return output
		else:
			self.errors.append("missing api_key and secret_key in the constructor")
			return None


### Create an object for connecting to Cloudstack
cs = CloudStack(
	protocol=conf.get('CLOUDSTACK', 'protocol'), 
	host=conf.get('CLOUDSTACK', 'host'), 
	uri=conf.get('CLOUDSTACK', 'uri'), 
	api_key=conf.get('CLOUDSTACK', 'api_key'), 
	secret_key=cs_secret_key, 
	logging=conf.getboolean('CLOUDSTACK', 'logging'), 
	async_poll_interval=conf.getint('CLOUDSTACK', 'async_poll_interval'))

### Update the running.conf file
conf.read("./running.conf") # make sure we have everything from this file already
with open('running.conf', 'wb') as f:
	conf.write(f) # update the file to include any changes we have made

