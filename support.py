# Copyright (C) 2006, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, sys, tempfile, shutil, traceback
from xml.dom import minidom, XMLNS_NAMESPACE, Node

from zeroinstall.injector.model import Interface, Implementation, Dependency, EnvironmentBinding, escape
from zeroinstall.injector import namespaces, basedir, reader
from zeroinstall.injector.iface_cache import iface_cache
from zeroinstall import SafeException
from zeroinstall.injector import run
from zeroinstall.zerostore import Stores

ENV_FILE = '0compile-env.xml'
XMLNS_0COMPILE = 'http://zero-install.sourceforge.net/2006/namespaces/0compile'

def lookup(id):
	if id.startswith('/'):
		if os.path.isdir(id):
			return id
		raise SafeException("Directory '%s' no longer exists. Try '0compile setup'" % id)
	return iface_cache.stores.lookup(id)

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

class BuildEnv(object):
	__slots__ = ['doc', 'interface', 'interfaces', 'root_impl', 'srcdir',
		     'download_base_url', 'distdir']

	def __init__(self):
		self.doc = get_env_doc()
		root = self.doc.documentElement
		self.interface = root.getAttributeNS(None, 'interface')
		assert self.interface

		self.download_base_url = root.getAttributeNS(None, 'download-base-url')

		self.interfaces = {}
		for child in children(root, XMLNS_0COMPILE, 'interface'):
			iface = self.interface_from_elem(child)
			assert iface.uri not in self.interfaces
			self.interfaces[iface.uri] = iface

		assert self.interface in self.interfaces
		self.root_impl = self.chosen_impl(self.interface)

		if os.path.isdir('src'):
			self.srcdir = os.path.realpath('src')
		else:
			self.srcdir = lookup(self.root_impl.id)

		iface_name = os.path.basename(self.interface)
		if iface_name.endswith('.xml'):
			iface_name = iface_name[:-4]
		distdir_name = '%s-%s' % (iface_name.lower(), self.root_impl.get_version())
		assert '/' not in distdir_name
		self.distdir = os.path.realpath(distdir_name)
	
	def chosen_impl(self, uri):
		assert uri in self.interfaces
		impls = self.interfaces[uri].implementations.values()
		assert len(impls) == 1
		return impls[0]

	def interface_from_elem(self, elem):
		uri = elem.getAttributeNS(None, 'uri')

		iface = Interface(uri)

		impl_elems = list(children(elem, XMLNS_0COMPILE, 'implementation'))
		assert len(impl_elems) == 1
		impl_elem = impl_elems[0]

		impl = iface.get_impl(impl_elem.getAttributeNS(None, 'id'))
		impl.main = impl_elem.getAttributeNS(None, 'main') or None
		impl.version = reader.parse_version(impl_elem.getAttributeNS(None, 'version'))

		for x in impl_elem.attributes.values():
			impl.metadata[x.name] = x.value

		for dep_elem in children(impl_elem, XMLNS_0COMPILE, 'requires'):
			dep_uri = dep_elem.getAttributeNS(None, 'interface')
			dep = Dependency(dep_uri)
			impl.dependencies[dep_uri] = dep

			for e in children(dep_elem, XMLNS_0COMPILE, 'environment'):
				env = EnvironmentBinding(e.getAttributeNS(None, 'name'),
							 e.getAttributeNS(None, 'insert'),
							 e.getAttributeNS(None, 'default') or None)
				dep.bindings.append(env)

		return iface

def depth(node):
	root = node.ownerDocument.documentElement
	depth = 0
	while node and node is not root:
		node = node.parentNode
		depth += 1
	return depth
