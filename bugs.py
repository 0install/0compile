# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__
from logging import info

from support import *

def do_reportbug(args):
	"""reportbug"""
	buildenv = BuildEnv()

	log_name = 'build/build-failure.log'
	build_log = file(log_name)
	log_text = build_log.read()
	build_log.close()
	
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

__main__.commands.append(do_reportbug)
