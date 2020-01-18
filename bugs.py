# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import os, __main__, codecs
from os.path import join

from support import BuildEnv

def do_report_bug(args):
	"""report-bug"""
	buildenv = BuildEnv()

	log_name = join('build', 'build-failure.log')
	build_log = codecs.open(log_name, 'r', 'utf-8')
	log_text = build_log.read()
	build_log.close()

	build_env_xml_file = join(buildenv.metadir, 'build-environment.xml')
	if os.path.exists(build_env_xml_file):
		with open(build_env_xml_file, 'r') as build_env_xml:
			log_text += '\n\nSelected versions:\n' + build_env_xml.read()
	else:
		log_text += '\n\n"%s" file not found' % build_env_xml_file
	
	log_text = codecs.encode(log_text, 'utf-8')

	import urllib.request, urllib.parse, urllib.error
	from urllib.request import urlopen

	print("Sending contents of %s file to default bug reporting site..." % log_name)

	stream = urlopen('http://api.0install.net/api/report-bug/',
		urllib.parse.urlencode({
		'uri': buildenv.interface,
		'body': log_text}).encode())
	print(stream.read())
	stream.close()

__main__.commands.append(do_report_bug)
