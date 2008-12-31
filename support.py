# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import os, sys, tempfile, shutil, traceback
from os.path import join
from logging import info

from zeroinstall.injector import model, selections, qdom
from zeroinstall.injector.model import Interface, Implementation, EnvironmentBinding, escape
from zeroinstall.injector import namespaces, reader
try:
	from zeroinstall.injector import basedir
except ImportError:
	from zeroinstall.support import basedir

from zeroinstall.injector.iface_cache import iface_cache
from zeroinstall import SafeException
from zeroinstall.injector import run
from zeroinstall.zerostore import Stores, Store, NotStored

ENV_FILE = '0compile-env.xml'
XMLNS_0COMPILE = 'http://zero-install.sourceforge.net/2006/namespaces/0compile'

if os.path.isdir('dependencies'):
	iface_cache.stores.stores.append(Store(os.path.realpath('dependencies')))

def lookup(id):
	if id.startswith('/'):
		if os.path.isdir(id):
			return id
		raise SafeException("Directory '%s' no longer exists. Try '0compile setup'" % id)
	try:
		return iface_cache.stores.lookup(id)
	except NotStored, ex:
		raise NotStored(str(ex) + "\nHint: try '0compile setup'")

# No longer used
def get_cached_iface_path(uri):
	if uri.startswith('/'):
		if not os.path.isfile(uri):
			raise SafeException("Local source interface '%s' does not exist!" % uri)
		return uri
	else:
		path = basedir.load_first_cache(namespaces.config_site, 'interfaces', escape(uri))
		if path and os.path.isfile(path):
			return path
		raise SafeException("Interface '%s' not found in cache. Hint: try '0compile setup'" % uri)

def ensure_dir(d):
	if os.path.isdir(d): return
	if os.path.exists(d):
		raise SafeException("'%s' exists, but is not a directory!" % d)
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

	USE_PLASH = 'USE_PLASH_0COMPILE'

	assert prog.startswith('/')
	_pola_run = find_in_path('pola-run')

	if _pola_run is None:
		print "Not using sandbox (plash not installed)"
		use_plash = False
	else:
		use_plash = os.environ.get(USE_PLASH, '').lower() or 'not set'
		if use_plash in ('not set', 'false'):
			print "Not using plash: $%s is %s" % (USE_PLASH, use_plash)
			use_plash = False
		elif use_plash == 'true':
			use_plash = True
		else:
			raise Exception('$%s must be "true" or "false", not "%s"' % (USE_PLASH, use_plash))

	if not use_plash:
		os.execlp(prog, prog, *args)
	
	print "Using plash to sandbox the build..."
	
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

def get_arch_name():
	uname = os.uname()
	target_os, target_machine = uname[0], uname[-1]
	if target_machine in ('i585', 'i686'):
		target_machine = 'i486'	# (sensible default)
	return target_os + '-' + target_machine

class BuildEnv(object):
	__slots__ = ['doc', 'selections', 'root_impl', 'orig_srcdir', 'user_srcdir', 'version_modifier',
		     'download_base_url', 'distdir', 'metadir', 'local_iface_file', 'iface_name',
		     'target_arch', 'archive_stem']

	interface = property(lambda self: self.selections.interface)

	def __init__(self):
		if not os.path.isfile(ENV_FILE):
			raise SafeException("Run 0compile from a directory containing a '%s' file" % ENV_FILE)
		self.doc = qdom.parse(file(ENV_FILE))
		if self.doc.name == 'build-environment':
			raise SafeException(("Sorry, this %s file is in an old format that is no longer supported. "
					     "Please delete it and try again.") % os.path.abspath(ENV_FILE))
		self.selections = selections.Selections(self.doc)

		self.download_base_url = self.doc.getAttribute(XMLNS_0COMPILE + ' download-base-url')

		self.version_modifier = self.doc.getAttribute(XMLNS_0COMPILE + ' version-modifier')

		self.root_impl = self.selections.selections[self.interface]
		self.orig_srcdir = os.path.realpath(lookup(self.root_impl.id))
		self.user_srcdir = None

		if os.path.isdir('src'):
			self.user_srcdir = os.path.realpath('src')
			if self.user_srcdir == self.orig_srcdir or \
			   self.user_srcdir.startswith(self.orig_srcdir + '/') or \
			   self.orig_srcdir.startswith(self.user_srcdir + '/'):
				info("Ignoring 'src' directory because it coincides with %s",
					self.orig_srcdir)
				self.user_srcdir = None
			else:
				if not self.version_modifier:
					self.version_modifier = '-1'

		self.target_arch = get_arch_name()

		self.iface_name = os.path.basename(self.interface)
		if self.iface_name.endswith('.xml'):
			self.iface_name = self.iface_name[:-4]
		self.iface_name = self.iface_name.replace(' ', '-')
		if self.iface_name.endswith('-src'):
			self.iface_name = self.iface_name[:-4]

		self.archive_stem = '%s-%s-%s%s' % (self.iface_name.lower(), self.target_arch.lower(), self.root_impl.version, self.version_modifier or "")

		distdir_name = 'dist-' + get_arch_name().lower()
		assert '/' not in distdir_name
		self.distdir = os.path.realpath(distdir_name)

		metadir = self.doc.getAttribute(XMLNS_0COMPILE + ' metadir')
		if metadir is None:
			metadir = '0install'
		assert not metadir.startswith('/')
		self.metadir = join(self.distdir, metadir)
		self.local_iface_file = join(self.metadir, '%s.xml' % self.iface_name)
	
	def chosen_impl(self, uri):
		assert uri in self.selections.selections
		return self.selections.selections[uri]

	local_download_iface = property(lambda self: '%s-%s%s.xml' % (self.iface_name, self.root_impl.version, self.version_modifier or ""))

def depth(node):
	root = node.ownerDocument.documentElement
	depth = 0
	while node and node is not root:
		node = node.parentNode
		depth += 1
	return depth

if hasattr(model, 'format_version'):
	format_version = model.format_version
	parse_version = model.parse_version
else:
	def format_version(v):
		return '.'.join(v)
	parse_version = reader.parse_version

def parse_bool(s):
	if s == 'true': return True
	if s == 'false': return False
	raise SafeException('Expected "true" or "false" but got "%s"' % s)

