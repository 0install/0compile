# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import os, sys, __main__
from logging import info
from optparse import OptionParser
import shutil

from zeroinstall import SafeException

from support import BuildEnv, spawn_and_check

pubish_command = os.environ["ZI_COMPILE_0PUBLISH"]

def do_publish(args):
	"""publish [ DOWNLOAD-BASE-URL ]"""

	parser = OptionParser(usage="usage: %prog publish [options] [ DOWNLOAD-BASE-URL ]")

	parser.add_option('', "--target-feed", help="name of output feed file to create", metavar='FILE')
	(options, args2) = parser.parse_args(args)

	buildenv = BuildEnv()
	if len(args2) == 1:
		buildenv.config.set('compile', 'download-base-url', args2[0])
		buildenv.save()
	elif len(args2) > 1:
		parser.print_help()
		sys.exit(1)

	download_base_url = buildenv.download_base_url or None

	if download_base_url:
		info("Using download base URL: %s", download_base_url)

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

	target_feed = options.target_feed or buildenv.local_download_iface

	if download_base_url:
		download_url = os.path.join(download_base_url, archive_name)
	else:
		download_url = archive_name
	shutil.copyfile(buildenv.local_iface_file, target_feed)
	
	# XXX: we're assuming that 0publish requires the same version of Python as
	# 0compile. This is currently needed for Arch Linux, but long-term we need to
	# use the <runner>.
	spawn_and_check(sys.executable, [
		pubish_command,
		target_feed,
		'--archive-url', download_url,
		'--archive-extract', buildenv.archive_stem])

	if options.target_feed is None:
		# If --target-feed is used this is probably a script, so don't print
		# out hints.
		if download_base_url:
			print "Now upload '%s' as:\n%s\n" % (archive_name, download_url)
			print "Once uploaded, you can download and run with:"
			print "0launch %s" % target_feed
		else:
			print "Generated archive '%s' and feed '%s'." % (archive_name, target_feed)
			print "Upload it to a repository with:"
			print "0repo add %s" % target_feed

__main__.commands.append(do_publish)
