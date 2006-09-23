# Copyright (C) 2006, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import sys, os, __main__
from logging import info
from xml.dom import minidom

from zeroinstall.injector.model import Interface, Implementation, Dependency, EnvironmentBinding
from zeroinstall.zerostore import Stores

from support import *

stores = Stores()
def lookup(id):
	if id.startswith('/'):
		if os.path.isdir(id):
			return id
		raise SafeException("Directory '%s' no longer exists. Try '0compile setup'" % id)
	return stores.lookup(id)

class BuildEnv(object):
	__slots__ = ['interface', 'interfaces', 'main', 'srcdir']

	def __init__(self):
		doc = get_env_doc()
		root = doc.documentElement
		self.interface = root.getAttributeNS(None, 'interface')
		assert self.interface

		self.interfaces = {}
		for child in children(root, XMLNS_0COMPILE, 'interface'):
			iface = self.interface_from_elem(child)
			assert iface.uri not in self.interfaces
			self.interfaces[iface.uri] = iface

		assert self.interface in self.interfaces
		root_impl = self.chosen_impl(self.interface)
		main = root_impl.main
		assert main

		self.main = os.path.join(lookup(root_impl.id), main)
		self.srcdir = os.path.dirname(self.main)

		print self.main
	
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

def env(name, value):
	info('Setting %s="%s"', name, value)
	os.environ[name] = value

def do_env_binding(binding, path):
	os.environ[binding.name] = binding.get_value(path,
					os.environ.get(binding.name, None))
	info("%s=%s", binding.name, os.environ[binding.name])

def do_build_internal():
	"""build-internal"""

	buildenv = BuildEnv()

	distdir = os.path.realpath('dist')
	builddir = os.path.realpath('build')

	env('BUILDDIR', builddir)
	env('DISTDIR', distdir)
	env('SRCDIR', buildenv.srcdir)
	os.chdir(builddir)

	for needed_iface in buildenv.interfaces:
		impl = buildenv.chosen_impl(needed_iface)
		assert impl
		for dep in impl.dependencies.values():
			dep_iface = buildenv.interfaces[dep.interface]
			for b in dep.bindings:
				if isinstance(b, EnvironmentBinding):
					dep_impl = buildenv.chosen_impl(dep.interface)
					do_env_binding(b, lookup(dep_impl.id))

	os.execv(buildenv.main, [buildenv.main])

def do_build(args):
	"""build"""
	if args:
		if args == ['internal']:
			return do_build_internal()
		raise __main__.UsageError()

	buildenv = BuildEnv()

	distdir = os.path.realpath('dist')
	builddir = os.path.realpath('build')

	ensure_dir(builddir)
	ensure_dir(distdir)

	tmpdir = tempfile.mkdtemp(prefix = '0compile-')
	try:
		readable = ['.', os.path.dirname(__file__)]
		writable = ['build', 'dist', tmpdir]
		env('TMPDIR', '/tmp')	# Plash maps this to tmpdir

		for iface in buildenv.interfaces:
			readable.append(lookup(buildenv.chosen_impl(iface).id))

		options = []
		if __main__.options.verbose:
			options.append('--verbose')
		spawn_maybe_sandboxed(readable, writable, tmpdir, sys.executable, [sys.argv[0]] + options + ['build', 'internal'])
	finally:
		info("Deleting temporary directory '%s'" % tmpdir)
		shutil.rmtree(tmpdir)

__main__.commands.append(do_build)
