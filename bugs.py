# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import os, __main__
from os.path import join

from support import BuildEnv

def do_report_bug(args):
	"""report-bug"""
	buildenv = BuildEnv()

	log_name = 'build/build-failure.log'
	build_log = file(log_name)
	log_text = build_log.read()
	build_log.close()

	build_env_xml_file = join(buildenv.metadir, 'build-environment.xml')
	if os.path.exists(build_env_xml_file):
		build_env_xml = file(build_env_xml_file)
		log_text += '\n\nSelected versions:\n' + build_env_xml.read()
		build_env_xml.close()
	else:
		log_text += '\n\n"%s" file not found' % build_env_xml_file
	
	import urllib
	from urllib2 import urlopen

	print "Sending contents of %s file to default bug tracker..." % log_name

	stream = urlopen('http://sourceforge.net/tracker/index.php',
		urllib.urlencode({
		'group_id': '76468',
		'atid': '905152',
		'func': 'postadd',
		'is_private': '0',
		'summary': log_text.split('\n', 1)[0],	# First line of log
		'details': log_text}))
	stream.read()
	stream.close()

__main__.commands.append(do_report_bug)
