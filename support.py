# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import os, sys, tempfile, shutil, traceback
import subprocess
from os.path import join
from logging import info
import ConfigParser

from zeroinstall.injector import model, selections, qdom
from zeroinstall.injector.model import Interface, Implementation, EnvironmentBinding, escape
from zeroinstall.injector import namespaces, reader
from zeroinstall.support import basedir

from zeroinstall.injector.iface_cache import iface_cache
from zeroinstall import SafeException
from zeroinstall.injector import run
from zeroinstall.zerostore import Stores, Store, NotStored

ENV_FILE = '0compile.properties'
XMLNS_0COMPILE = 'http://zero-install.sourceforge.net/2006/namespaces/0compile'

if os.path.isdir('dependencies'):
	iface_cache.stores.stores.append(Store(os.path.realpath('dependencies')))

class NoImpl:
	id = "none"
	version = "none"
no_impl = NoImpl()

def lookup(id):
	if id.startswith('/'):
		if os.path.isdir(id):
			return id
		raise SafeException("Directory '%s' no longer exists. Try '0compile setup'" % id)
	try:
		return iface_cache.stores.lookup(id)
	except NotStored, ex:
		raise NotStored(str(ex) + "\nHint: try '0compile setup'")

def ensure_dir(d, clean = False):
	if os.path.isdir(d):
		if clean:
			print "Removing", d
			shutil.rmtree(d)
		else:
			return
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

class BuildEnv:
	def __init__(self, need_config = True):
		if need_config and not os.path.isfile(ENV_FILE):
			raise SafeException("Run 0compile from a directory containing a '%s' file" % ENV_FILE)

		self.config = ConfigParser.RawConfigParser()
		self.config.add_section('compile')
		self.config.set('compile', 'download-base-url', '')
		self.config.set('compile', 'version-modifier', '')
		self.config.set('compile', 'interface', '')
		self.config.set('compile', 'selections', '')
		self.config.set('compile', 'metadir', '0install')

		self.config.read(ENV_FILE)

		self._selections = None

		return

	@property
	def iface_name(self):
		iface_name = os.path.basename(self.interface)
		if iface_name.endswith('.xml'):
			iface_name = iface_name[:-4]
		iface_name = iface_name.replace(' ', '-')
		if iface_name.endswith('-src'):
			iface_name = iface_name[:-4]
		return iface_name

	interface = property(lambda self: self.config.get('compile', 'interface'))

	@property
	def distdir(self):
		distdir_name = '%s-%s' % (self.iface_name.lower(), get_arch_name().lower())
		assert '/' not in distdir_name
		return os.path.realpath(distdir_name)

	@property
	def metadir(self):
		metadir = self.config.get('compile', 'metadir')
		assert not metadir.startswith('/')
		return join(self.distdir, metadir)

	@property
	def local_iface_file(self):
		return join(self.metadir, self.iface_name + '.xml')

	@property
	def target_arch(self):
		return get_arch_name()

	@property
	def version_modifier(self):
		vm = self.config.get('compile', 'version-modifier')
		if vm: return vm
		if self.user_srcdir:
			return '-1'
		return ''

	@property
	def archive_stem(self):
		# Use the version that we actually built, not the version we would build now
		feed = self.load_built_feed()
		assert len(feed.implementations) == 1
		version = feed.implementations.values()[0].get_version()
		return '%s-%s-%s' % (self.iface_name.lower(), self.target_arch.lower(), version)

	def load_built_feed(self):
		path = self.local_iface_file
		stream = file(path)
		try:
			feed = model.ZeroInstallFeed(qdom.parse(stream), local_path = path)
		finally:
			stream.close()
		return feed

	def load_built_selections(self):
		path = join(self.metadir, 'build-environment.xml')
		if os.path.exists(path):
			stream = file(path)
			try:
				return selections.Selections(qdom.parse(stream))
			finally:
				stream.close()
		return None

	@property
	def download_base_url(self):
		return self.config.get('compile', 'download-base-url')
	
	def chosen_impl(self, uri):
		sels = self.get_selections()
		assert uri in sels.selections
		return sels.selections[uri]

	@property
	def local_download_iface(self):
		impl, = self.load_built_feed().implementations.values()
		return '%s-%s.xml' % (self.iface_name, impl.get_version())

	def save(self):
		stream = file(ENV_FILE, 'w')
		try:
			self.config.write(stream)
		finally:
			stream.close()

	def get_selections(self, prompt = False):
		if self._selections:
			assert not prompt
			return self._selections

		selections_file = self.config.get('compile', 'selections')
		if selections_file:
			if prompt:
				raise SafeException("Selections are fixed by %s" % selections_file)
			stream = file(selections_file)
			try:
				self._selections = selections.Selections(qdom.parse(stream))
			finally:
				stream.close()
			from zeroinstall.injector import fetch
			from zeroinstall.injector.handler import Handler
			handler = Handler()
			fetcher = fetch.Fetcher(handler)
			blocker = self._selections.download_missing(iface_cache, fetcher)
			if blocker:
				print "Waiting for selected implementations to be downloaded..."
				handler.wait_for_blocker(blocker)
		else:
			options = []
			if prompt:
				options.append('--gui')
			child = subprocess.Popen(['0launch', '--source', '--get-selections'] + options + [self.interface], stdout = subprocess.PIPE)
			try:
				self._selections = selections.Selections(qdom.parse(child.stdout))
			finally:
				if child.wait():
					raise SafeException("0launch --get-selections failed (exit code %d)" % child.returncode)

		self.root_impl = self._selections.selections[self.interface]

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

		return self._selections

	def get_build_changes(self):
		sels = self.get_selections()
		old_sels = self.load_built_selections()
		changes = []
		if old_sels:
			# See if things have changed since the last build
			all_ifaces = set(sels.selections) | set(old_sels.selections)
			for x in all_ifaces:
				old_impl = old_sels.selections.get(x, no_impl)
				new_impl = sels.selections.get(x, no_impl)
				if old_impl.version != new_impl.version:
					changes.append("Version change for %s: %s -> %s" % (x, old_impl.version, new_impl.version))
				elif old_impl.id != new_impl.id:
					changes.append("Version change for %s: %s -> %s" % (x, old_impl.id, new_impl.id))
		return changes

def depth(node):
	root = node.ownerDocument.documentElement
	depth = 0
	while node and node is not root:
		node = node.parentNode
		depth += 1
	return depth

format_version = model.format_version
parse_version = model.parse_version

def parse_bool(s):
	if s == 'true': return True
	if s == 'false': return False
	raise SafeException('Expected "true" or "false" but got "%s"' % s)
