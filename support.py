# Copyright (C) 2006, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, sys, tempfile, shutil, traceback

from zeroinstall import SafeException
from zeroinstall.injector import run

ENV_FILE = '0compile-env.xml'
XMLNS_0COMPILE = 'http://zero-install.sourceforge.net/2006/namespaces/0compile'

def ensure_dir(d):
	if os.path.isdir(d): return
	if os.path.exists(d):
		raise SafeException("'%s' exitst, but is not a directory!" % d)
	os.mkdir(d)

def spawn(policy, main, args):
	child = os.fork()
	if child == 0:
		try:
			try:
				run.execute(policy, args, main = main)
			except SafeException, ex:
				print str(ex)
			except:
				traceback.print_exc()
		finally:
			os._exit(1)
	pid, status = os.waitpid(child, 0)
	assert pid == child
	if os.WIFEXITED(status):
		exit_code = os.WEXITSTATUS(status)
		if exit_code == 0:
			return
		else:
			raise SafeException('Command failed with exit status %d' % exit_code)
	else:
		raise SafeException('Command failed with signal %d' % WTERMSIG(status))
