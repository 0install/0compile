# Copyright (C) 2006, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import sys, os, __main__
from logging import info
from xml.dom import minidom

from support import *

def env(name, value):
	info('Setting %s="%s"', name, value)
	os.environ[name] = value

def do_env_binding(binding, path):
	os.environ[binding.name] = binding.get_value(path,
					os.environ.get(binding.name, None))
	info("%s=%s", binding.name, os.environ[binding.name])

def do_build_internal(args):
	"""build-internal"""
	import getpass, socket, time

	buildenv = BuildEnv()

	distdir = os.path.realpath('dist')
	builddir = os.path.realpath('build')

	# Create build-environment.xml file
	root = buildenv.doc.documentElement
	info = buildenv.doc.createElementNS(XMLNS_0COMPILE, 'build-info')
	root.appendChild(buildenv.doc.createTextNode('  '))
	root.appendChild(info)
	root.appendChild(buildenv.doc.createTextNode('\n'))
	info.setAttributeNS(None, 'time', time.strftime('%Y-%m-%d %H:%M').strip())
	info.setAttributeNS(None, 'host', socket.getfqdn())
	info.setAttributeNS(None, 'user', getpass.getuser())
	uname = os.uname()
	info.setAttributeNS(None, 'arch', '%s-%s' % (uname[0], uname[4]))
	buildenv.doc.writexml(file('dist/build-environment.xml', 'w'))

	# Create local binary interface file
	

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

	if args == ['--shell']:
		spawn_and_check(find_in_path('sh'), [])
	else:
		# GNU build process
		spawn_and_check(buildenv.main, ['--prefix', distdir])
		spawn_and_check(find_in_path('make'), [])
		spawn_and_check(find_in_path('make'), ['install'])

def do_build(args):
	"""build [ --nosandbox ] [ shell ]"""
	buildenv = BuildEnv()

	distdir = os.path.realpath('dist')
	builddir = os.path.realpath('build')

	ensure_dir(builddir)
	ensure_dir(distdir)

	if args[:1] == ['--nosandbox']:
		return do_build_internal(args[1:])

	tmpdir = tempfile.mkdtemp(prefix = '0compile-')
	try:
		my_dir = os.path.dirname(__file__)
		readable = ['.', my_dir]
		writable = ['build', 'dist', tmpdir]
		env('TMPDIR', tmpdir)
		env('PATH', os.path.join(my_dir, 'bin') + ':' + os.environ['PATH'])

		for iface in buildenv.interfaces:
			readable.append(lookup(buildenv.chosen_impl(iface).id))

		options = []
		if __main__.options.verbose:
			options.append('--verbose')
		spawn_maybe_sandboxed(readable, writable, tmpdir, sys.executable, [sys.argv[0]] + options + ['build', '--nosandbox'] + args)
	finally:
		info("Deleting temporary directory '%s'" % tmpdir)
		shutil.rmtree(tmpdir)

__main__.commands.append(do_build)
