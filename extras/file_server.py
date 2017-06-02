#!/usr/bin/env python

## ----------------------
##  INSTALL DEPENDANCIES
## ----------------------
## $ pip install argparse
## $ pip install bottle
## $ pip install cherrypy
##
## Author: Will Stevens

import argparse
import bottle
import os
import sys
# depends on 'cherrypy' server

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--include", type=str, help="require the file name to include this string")
parser.add_argument("-x", "--exclude", type=str, help="require the file name to exclude this string")
args = parser.parse_args()

# index which lists all of the files in this directory
@bottle.route('/')
def index():
	""" Outputs a link for each file in the current directory which match the 'include' and 'exclude' rules. """
	output = '<div style="font-family:monospace; padding:10px;">'
	for file_name in os.listdir('./'):
		include_bool = True
		if args.include:
			include_bool = args.include in file_name
		exclude_bool = True
		if args.exclude:
			exclude_bool = args.exclude not in file_name
		if file_name != __file__ and os.path.isfile(file_name) and include_bool and exclude_bool:
			output = '%s<a href="/%s">%s</a><br />' % (output, file_name, file_name)
	return output+'</div>'

# serve the requested file
@bottle.route('/<filepath:path>')
def serve_file(filepath):
	""" Download the requested file. """
	bottle.response.set_header("Content-Type", "application/octet-stream")
	bottle.response.set_header("Content-Disposition", "attachment; filename=\""+filepath+"\";" )
	bottle.response.set_header("Content-Transfer-Encoding", "binary")
	return bottle.static_file(filepath, root='./', download=True)

# start the server
bottle.run(
	server='cherrypy', 
	host='0.0.0.0', 
	port=80, 
	reloader=False, 
	debug=False)
