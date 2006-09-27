# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__
from logging import info
from support import *

def do_copy_src(args):
	"""copy-src"""
	if args:
		raise __main__.UsageError()

	buildenv = BuildEnv()

	src_impl = buildenv.chosen_impl(buildenv.interface)
	assert src_impl
	path = lookup(src_impl.id)
	assert path

	new_src = os.path.realpath('src')	# Just for better messages
	if os.path.exists(new_src):
		raise SafeException("Directory '%s' already exists!" % new_src)
	shutil.copytree(path, 'src')
	# Make all files writable by the owner
	for root, dirs, files in os.walk('src'):
		for f in files:
			path = os.path.join(root, f)
			os.chmod(path, os.stat(path).st_mode | 0200)

	print "Copied as '%s'" % new_src

def do_diff(args):
	"""diff"""
	if args:
		raise __main__.UsageError()
	buildenv = BuildEnv()

	if not os.path.isdir('src'):
		raise SafeException('No local src directory to diff against!')
	new_src = os.path.realpath('src')

	src_impl = buildenv.chosen_impl(buildenv.interface)
	assert src_impl

	prog = find_in_path('diff')
	args = ['-ur', lookup(src_impl.id), new_src]

	status = os.spawnv(os.P_WAIT, prog, [prog] + args)
	if status == 0:
		return False
	elif status == 1:
		return True
	elif status > 1:
		raise SafeException("Program '%s' failed with exit code %d" % (prog, status))
	elif status < 0:
		raise SafeException("Program '%s' failed with signal %d" % (prog, -status))

__main__.commands += [do_copy_src, do_diff]
