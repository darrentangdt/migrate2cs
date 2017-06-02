#!/usr/bin/env python

# Author: Will Stevens - wstevens@cloudops.com
from ConfigParser import ConfigParser
from lib.common import *
from cpbmapi import API as CPBM_API
import sys

# setup the conf object and set default values...
conf = ConfigParser()
conf.add_section('CPBM')
#conf.set('CPBM', 'logging', 'True')
#conf.set('CPBM', 'log_file', './logs/cpbm_request.log')
#conf.set('CPBM', 'clear_log', 'True')

# read in config if it exists
conf.read("./settings.conf")

if (conf.has_option('CPBM', 'endpoint') or conf.has_option('CPBM', 'api_key') or
        conf.has_option('CPBM', 'secret_key') or conf.has_option('CPBM', 'secret_key_hash')):

    # get and hash the password(s)...
    cpbm_secret_key = password_hash('CPBM', 'secret_key', 'secret_key_hash')

    # require an 'api_key' and a 'secret_key' to use this lib
    if not conf.has_option('CPBM', 'endpoint'):
        sys.exit("Config required in settings.conf: [CPBM] -> endpoint")
    if not conf.has_option('CPBM', 'api_key'):
        sys.exit("Config required in settings.conf: [CPBM] -> api_key")
    if not cpbm_secret_key:
        sys.exit("Config required in settings.conf: [CPBM] -> secret_key")

    ### Create an object for connecting to CPBM
    cpbm = CPBM_API(api_key=conf.get('CPBM', 'api_key'),
                    secret_key=cpbm_secret_key,
                    endpoint=conf.get('CPBM', 'endpoint'))
                    #logging=conf.getboolean('CPBM', 'logging'),
                    #log=conf.get('CPBM', 'log_file'),
                    #clear_log=conf.getboolean('CPBM', 'clear_log'))

    ### Update the running.conf file
    conf.read("./running.conf") # make sure we have everything from this file already
    with open('running.conf', 'wb') as f:
        conf.write(f) # update the file to include any changes we have made
else:
    cpbm = None