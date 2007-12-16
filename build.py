# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__, time, shutil
from os.path import join
from logging import info
from xml.dom import minidom, XMLNS_NAMESPACE

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

	build_env_xml = join(buildenv.metadir, 'build-environment.xml')

	buildenv_doc = buildenv.selections.toDOM()

	# Create build-environment.xml file
	root = buildenv_doc.documentElement
	info = buildenv_doc.createElementNS(XMLNS_0COMPILE, 'build-info')
	root.appendChild(info)
	info.setAttributeNS(None, 'time', time.strftime('%Y-%m-%d %H:%M').strip())
	info.setAttributeNS(None, 'host', socket.getfqdn())
	info.setAttributeNS(None, 'user', getpass.getuser())
	uname = os.uname()
	info.setAttributeNS(None, 'arch', '%s-%s' % (uname[0], uname[4]))
	stream = file(build_env_xml, 'w')
	buildenv_doc.writexml(stream, addindent="  ", newl="\n")
	stream.close()

	# Create local binary interface file
	src_iface = iface_cache.get_interface(buildenv.interface)
	src_impl = buildenv.chosen_impl(buildenv.interface)
	write_sample_interface(buildenv, src_iface, src_impl)

	# Create the patch
	orig_impl = buildenv.chosen_impl(buildenv.interface)
	patch_file = join(buildenv.metadir, 'from-%s.patch' % orig_impl.version)
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

	for needed_iface in buildenv.selections.selections:
		impl = buildenv.chosen_impl(needed_iface)
		assert impl
		for dep in impl.dependencies:
			dep_iface = buildenv.selections.selections[dep.interface]
			for b in dep.bindings:
				if isinstance(b, EnvironmentBinding):
					dep_impl = buildenv.chosen_impl(dep.interface)
					do_env_binding(b, lookup(dep_impl.id))

	if args == ['--shell']:
		spawn_and_check(find_in_path('sh'), [])
	else:
		command = buildenv.doc.getAttribute(XMLNS_0COMPILE + ' command')

		# Remove any existing log files
		for log in ['build.log', 'build-success.log', 'build-failure.log']:
			if os.path.exists(log):
				os.unlink(log)

		# Run the command, copying output to a new log
		log = file('build.log', 'w')
		try:
			print >>log, "Build log for %s-%s" % (src_iface.get_name(),
							      src_impl.version)
			print >>log, "\nBuilt using 0compile-%s" % __main__.version
			print >>log, "\nBuild system: " + ', '.join(uname)
			print >>log, "\n%s:\n" % ENV_FILE
			shutil.copyfileobj(file("../" + ENV_FILE), log)

			log.write('\n')

			if os.path.exists(patch_file):
				print >>log, "\nPatched with:\n"
				shutil.copyfileobj(file(patch_file), log)
				log.write('\n')

			print "Executing: " + command
			print >>log, "Executing: " + command

			# Tee the output to the console and to the log
			from popen2 import Popen4
			child = Popen4(command)
			child.tochild.close()
			while True:
				data = os.read(child.fromchild.fileno(), 100)
				if not data: break
				sys.stdout.write(data)
				log.write(data)
			status = child.wait()
			failure = None
			if os.WIFEXITED(status):
				exit_code = os.WEXITSTATUS(status)
				if exit_code == 0:
					print >>log, "Build successful"
				else:
					failure = "Build failed with exit code %d" % exit_code
			else:
				failure = "Build failure: exited due to signal %d" % os.WTERMSIG(status)
			if failure:
				print >>log, failure
				os.rename('build.log', 'build-failure.log')
				raise SafeException("Command '%s': %s" % (command, failure))
			else:
				os.rename('build.log', 'build-success.log')
		finally:
			log.close()

def do_build(args):
	"""build [ --nosandbox ] [ --shell ]"""
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

		# Why did we need this?
		#readable.append(get_cached_iface_path(buildenv.interface))

		for selection in buildenv.selections.selections.values():
			readable.append(lookup(selection.id))

		options = []
		if __main__.options.verbose:
			options.append('--verbose')

		readable.append('/etc')	# /etc/ld.*

		spawn_maybe_sandboxed(readable, writable, tmpdir, sys.executable, [sys.argv[0]] + options + ['build', '--nosandbox'] + args)
	finally:
		info("Deleting temporary directory '%s'" % tmpdir)
		shutil.rmtree(tmpdir)

def write_sample_interface(buildenv, iface, src_impl):
	path = buildenv.local_iface_file
	target_arch = buildenv.target_arch

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
	main = buildenv.doc.getAttribute(XMLNS_0COMPILE + ' binary-main')
	if main:
		group.setAttributeNS(None, 'main', main)
	
	for d in src_impl.dependencies:
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
				
	group.setAttributeNS(None, 'arch', target_arch)
	impl_elem = addSimple(group, 'implementation')
	impl_elem.setAttributeNS(None, 'version', src_impl.version)

	if buildenv.version_modifier:
		impl_elem.setAttributeNS(None, 'version-modifier', buildenv.version_modifier)

	impl_elem.setAttributeNS(None, 'id', '..')
	impl_elem.setAttributeNS(None, 'released', time.strftime('%Y-%m-%d'))
	close(group)
	close(root)

	doc.writexml(file(path, 'w'))

__main__.commands.append(do_build)
