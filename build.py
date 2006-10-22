# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__, time
from os.path import join
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

	builddir = os.path.realpath('build')
	ensure_dir(buildenv.metadir)

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
	buildenv.doc.writexml(file(join(buildenv.metadir, 'build-environment.xml'), 'w'))

	# Create local binary interface file
	src_iface = iface_cache.get_interface(buildenv.interface)
	write_sample_interface(src_iface, buildenv.local_iface_file,
		buildenv.chosen_impl(buildenv.interface))

	# Create the patch
	orig_impl = buildenv.chosen_impl(buildenv.interface)
	patch_file = join(buildenv.distdir, '0install/from-%s.patch' % orig_impl.get_version())
	if os.path.isdir('src'):
		orig_src = lookup(orig_impl.id)
		# (ignore errors; will already be shown on stderr)
		os.system("diff -urN '%s' src > %s" %
			(orig_src.replace('\\', '\\\\').replace("'", "\\'"),
			 patch_file))
		if os.path.getsize(patch_file) == 0:
			os.unlink(patch_file)
	elif os.path.exists(patch_file):
		os.unlink(patch_file)

	env('BUILDDIR', builddir)
	env('DISTDIR', buildenv.distdir)
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
		command = buildenv.root_impl.metadata['command']
		print "Executing: " + command
		if os.system(command):
			raise SafeException("Build command '%s' failed (non-zero exit status)" % command)

def do_build(args):
	"""build [ --nosandbox ] [ shell ]"""
	buildenv = BuildEnv()

	builddir = os.path.realpath('build')

	ensure_dir(builddir)
	ensure_dir(buildenv.distdir)

	if args[:1] == ['--nosandbox']:
		return do_build_internal(args[1:])

	tmpdir = tempfile.mkdtemp(prefix = '0compile-')
	try:
		my_dir = os.path.dirname(__file__)
		readable = ['.', my_dir]
		writable = ['build', buildenv.distdir, tmpdir]
		env('TMPDIR', tmpdir)
		env('PATH', join(my_dir, 'bin') + ':' + os.environ['PATH'])

		readable.append(get_cached_iface_path(buildenv.interface))

		for iface in buildenv.interfaces:
			readable.append(lookup(buildenv.chosen_impl(iface).id))

		options = []
		if __main__.options.verbose:
			options.append('--verbose')

		readable.append('/etc')	# /etc/ld.*

		spawn_maybe_sandboxed(readable, writable, tmpdir, sys.executable, [sys.argv[0]] + options + ['build', '--nosandbox'] + args)
	finally:
		info("Deleting temporary directory '%s'" % tmpdir)
		shutil.rmtree(tmpdir)

def write_sample_interface(iface, path, src_impl):
	impl = minidom.getDOMImplementation()

	XMLNS_IFACE = namespaces.XMLNS_IFACE

	doc = impl.createDocument(XMLNS_IFACE, "interface", None)

	root = doc.documentElement
	root.setAttributeNS(XMLNS_NAMESPACE, 'xmlns', XMLNS_IFACE)

	def addSimple(parent, name, text = None):
		elem = doc.createElementNS(XMLNS_IFACE, name)

		parent.appendChild(doc.createTextNode('\n' + '  ' * (1 + depth(parent))))
		parent.appendChild(elem)
		if text:
			elem.appendChild(doc.createTextNode(text))
		return elem

	def close(element):
		element.appendChild(doc.createTextNode('\n' + '  ' * depth(element)))

	addSimple(root, 'name', iface.name)
	addSimple(root, 'summary', iface.summary)
	addSimple(root, 'description', iface.description)
	feed_for = addSimple(root, 'feed-for')
	feed_for.setAttributeNS(None, 'interface', iface.uri)

	group = addSimple(root, 'group')
	main = src_impl.metadata.get('binary-main')
	if main:
		group.setAttributeNS(None, 'main', main)
	
	for d in src_impl.dependencies.values():
		if parse_bool(d.metadata.get('include-binary', 'false')):
			requires = addSimple(group, 'requires')
			requires.setAttributeNS(None, 'interface', d.interface)
			for b in d.bindings:
				if isinstance(b, model.EnvironmentBinding):
					env_elem = addSimple(requires, 'environment')
					env_elem.setAttributeNS(None, 'name', b.name)
					env_elem.setAttributeNS(None, 'insert', b.insert)
					if b.default:
						env_elem.setAttributeNS(None, 'default', b.default)
				else:
					raise Exception('Unknown binding type ' + b)
			close(requires)
				

	uname = os.uname()
	target_os, target_machine = uname[0], uname[-1]
	if target_machine in ('i585', 'i686'):
		target_machine = 'i486'	# (sensible default)

	group.setAttributeNS(None, 'arch', '%s-%s' % (target_os, target_machine))
	impl_elem = addSimple(group, 'implementation')
	impl_elem.setAttributeNS(None, 'version', src_impl.get_version())
	impl_elem.setAttributeNS(None, 'id', '..')
	impl_elem.setAttributeNS(None, 'released', time.strftime('%Y-%m-%d'))
	close(group)
	close(root)

	doc.writexml(file(path, 'w'))

__main__.commands.append(do_build)
