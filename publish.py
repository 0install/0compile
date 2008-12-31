# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__
from logging import info
from xml.dom import minidom

from support import *

def do_publish(args):
	"""publish [ DOWNLOAD-BASE-URL ]"""
	buildenv = BuildEnv()
	if len(args) == 0:
		if not buildenv.download_base_url:
			raise SafeException("No download base set. Give the URL for a remote directory.")
	elif len(args) == 1:
		buildenv.download_base_url = args[0]
		doc = minidom.parse(file(ENV_FILE))
		doc.documentElement.setAttributeNS(XMLNS_0COMPILE, 'compile:download-base-url', args[0])
		doc.writexml(file(ENV_FILE, 'w'))

	info("Using download base URL: %s", buildenv.download_base_url)

	if not os.path.isdir(buildenv.distdir):
		raise SafeException("Directory '%s' does not exist. Try 'compile build'." % buildenv.distdir)

	distdir = os.path.basename(buildenv.distdir)
	archive_name = buildenv.archive_stem + '.tar.bz2'

	# Make all directories in the archive user writable
	for main, dirs, files in os.walk(distdir):
		os.chmod(main, os.stat(main).st_mode | 0200)

	import tarfile
	archive = tarfile.open(archive_name, mode = 'w:bz2')
	archive.add(distdir, buildenv.archive_stem)
	archive.close()

	download_url = os.path.join(buildenv.download_base_url, archive_name)
	shutil.copyfile(buildenv.local_iface_file, buildenv.local_download_iface)
	
	spawn_and_check(find_in_path('0launch'),
		['http://0install.net/2006/interfaces/0publish', buildenv.local_download_iface,
		'--archive-url', download_url,
		'--archive-extract', buildenv.archive_stem])

	print "Now upload '%s' as:\n%s\n" % (archive_name, download_url)

	print "Once uploaded, you can download and run with:"
	print "$ 0launch %s" % buildenv.local_download_iface

__main__.commands.append(do_publish)
