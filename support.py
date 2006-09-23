# Copyright (C) 2006, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, sys, tempfile, shutil, traceback
from xml.dom import minidom, XMLNS_NAMESPACE, Node

from zeroinstall import SafeException
from zeroinstall.injector import run

ENV_FILE = '0compile-env.xml'
XMLNS_0COMPILE = 'http://zero-install.sourceforge.net/2006/namespaces/0compile'

def ensure_dir(d):
	if os.path.isdir(d): return
	if os.path.exists(d):
		raise SafeException("'%s' exitst, but is not a directory!" % d)
	os.mkdir(d)

def find_in_path(prog):
	for d in os.environ['PATH'].split(':'):
		path = os.path.join(d, prog)
		if os.path.isfile(path):
			return path
	return None

def spawn_and_check(prog, args):
	status = os.spawnv(os.P_WAIT, prog, [prog] + args)
	if status > 0:
		raise SafeException("Program '%s' failed with exit code %d" % (prog, status))
	elif status < 0:
		raise SafeException("Program '%s' failed with signal %d" % (prog, -status))

def wait_for_child(child):
	"""Wait for child to exit and reap it. Throw an exception if it doesn't return success."""
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

def get_env_doc():
	if not os.path.isfile(ENV_FILE):
		raise SafeException("Run 0compile from a directory containing a '%s' file" % ENV_FILE)
	return minidom.parse(ENV_FILE)

def children(parent, uri, name):
	"""Yield all direct children with the given name."""
	for x in parent.childNodes:
		if x.nodeType == Node.ELEMENT_NODE and x.namespaceURI == uri and x.localName == name:
			yield x

def spawn_maybe_sandboxed(readable, writable, tmpdir, prog, args):
	child = os.fork()
	if child == 0:
		try:
			try:
				exec_maybe_sandboxed(readable, writable, tmpdir, prog, args)
			except:
				traceback.print_exc()
		finally:
			print >>sys.stderr, "Exec failed"
			os._exit(1)
	wait_for_child(child)

def exec_maybe_sandboxed(readable, writable, tmpdir, prog, args):
	"""execl prog, with (only) the 'writable' directories writable if sandboxing is available.
	The readable directories will be readable, as well as various standard locations.
	If no sandbox is available, run without a sandbox."""
	assert prog.startswith('/')
	_pola_run = find_in_path('pola-run')

	if _pola_run is None:
		os.execlp(prog, prog, *args)
	# We have pola-shell :-)
	pola_args = ['--prog', prog, '-B']
	for a in args:
		pola_args += ['-a', a]
	for r in readable:
		pola_args += ['-f', r]
	for w in writable:
		pola_args += ['-fw', w]
	pola_args += ['-tw', '/tmp', tmpdir]
	os.environ['TMPDIR'] = '/tmp'
	os.execl(_pola_run, _pola_run, *pola_args)
