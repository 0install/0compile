# Copyright (C) 2009, Thomas Leonard
# See http://0install.net/0compile.html

import __main__, shutil, os

from support import BuildEnv

def do_clean(args):
	"""clean"""
	if args:
		raise __main__.UsageError()

	buildenv = BuildEnv()

	for x in ['build', buildenv.distdir]:
		if os.path.exists(x):
			print("Removing '%s'" % os.path.basename(x))
			shutil.rmtree(x)

__main__.commands.append(do_clean)
