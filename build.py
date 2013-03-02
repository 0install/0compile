# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__, time, shutil, glob, codecs, subprocess
from os.path import join
from logging import info, warn
from xml.dom import minidom, XMLNS_NAMESPACE
from optparse import OptionParser
import tempfile

from zeroinstall import SafeException
from zeroinstall.injector import model, namespaces, run
from zeroinstall.injector.iface_cache import iface_cache

from support import BuildEnv, ensure_dir, XMLNS_0COMPILE, is_package_impl, parse_bool, depth, uname
from support import spawn_and_check, find_in_path, ENV_FILE, lookup, spawn_and_check_maybe_sandboxed, Prefixes

# If we have to modify any pkg-config files, we put the new versions in $TMPDIR/PKG_CONFIG_OVERRIDES
PKG_CONFIG_OVERRIDES = 'pkg-config-overrides'

def env(name, value):
	os.environ[name] = value
	print "%s=%s" % (name, value)

def do_env_binding(binding, path):
	if binding.insert is not None and path is None:
		# Skip insert bindings for package implementations
		return
	env(binding.name, binding.get_value(path, os.environ.get(binding.name, None)))

def correct_for_64bit(base, rel_path):
	"""If rel_path starts lib or usr/lib and doesn't exist, try with lib64 instead."""
	if os.path.exists(os.path.join(base, rel_path)):
		return rel_path

	if rel_path.startswith('lib/') or rel_path.startswith('usr/lib/'):
		new_rel_path = rel_path.replace('lib/', 'lib64/', 1)
		if os.path.exists(os.path.join(base, new_rel_path)):
			return new_rel_path

	return rel_path

def write_pc(name, lines):
	overrides_dir = os.path.join(os.environ['TMPDIR'], PKG_CONFIG_OVERRIDES)
	if not os.path.isdir(overrides_dir):
		os.mkdir(overrides_dir)
	stream = open(os.path.join(overrides_dir, name), 'w')
	stream.write(''.join(lines))
	stream.close()

def do_pkg_config_binding(binding, impl):
	if impl.id.startswith('package:'):
		return		# No bindings needed for native packages
	feed_name = impl.feed.split('/')[-1]
	path = lookup(impl)
	new_insert = correct_for_64bit(path, binding.insert)
	if new_insert != binding.insert:
		print "PKG_CONFIG_PATH dir <%s>/%s not found; using %s instead" % (feed_name, binding.insert, new_insert)
		binding = model.EnvironmentBinding(binding.name,
					new_insert,
					binding.default,
					binding.mode)

	orig_path = os.path.join(path, binding.insert)
	if os.path.isdir(orig_path):
		for pc in os.listdir(orig_path):
			stream = open(os.path.join(orig_path, pc))
			lines = stream.readlines()
			stream.close()
			for i, line in enumerate(lines):
				if '=' not in line: continue
				name, value = [x.strip() for x in line.split('=', 1)]
				if name == 'prefix' and os.path.isabs(value):
					print "Absolute prefix=%s in %s; overriding..." % (value, feed_name)
					lines[i] = 'prefix=' + os.path.join(
						path, os.path.splitdrive(value)[1][1:]) +'\n'
					write_pc(pc, lines)
					break
	do_env_binding(binding, path)

def shorten_dynamic_library_install_name(dylib_file):
	# Only need to change actual library, not links to it
	if os.path.islink(dylib_file):
		return
	otool_args = ['/usr/bin/otool', '-D', dylib_file]
	process = subprocess.Popen(otool_args, stdout=subprocess.PIPE)
	output, error = process.communicate()
	retcode = process.poll()
	for line in output.split('\n'):
		if not line.endswith(':'):
			value = line.strip()
			print "Absolute install name=%s in %s; fixing..." % (value, dylib_file)
			break
	shortname = os.path.basename(dylib_file)
	subprocess.check_call(['install_name_tool', '-id', shortname, dylib_file])

# After doing a build, remove the (dist) directory component from dynamic libraries
def shorten_dynamic_library_install_names():
	for root, dirs, files in os.walk(os.environ['DISTDIR']):
		if os.path.basename(root) == 'lib':
			for f in files:
				if f.endswith('.dylib'):
					info("Checking dynamic library '%s'", f)
					shorten_dynamic_library_install_name(os.path.join(root, f))

def fixup_generated_pkgconfig_file(pc_file):
	stream = open(pc_file)
	lines = stream.readlines()
	stream.close()
	for i, line in enumerate(lines):
		if '=' not in line: continue
		name, value = [x.strip() for x in line.split('=', 1)]
		if name == 'prefix' and os.path.isabs(value):
			print "Absolute prefix=%s in %s; fixing..." % (value, pc_file)
			rel_path = os.path.relpath(value, os.path.dirname(pc_file))
			lines[i] = 'prefix=' + os.path.join(
				'${pcfiledir}', rel_path) + '\n'
			write_pc(pc_file, lines)
			break

# After doing a build, check that we didn't generate pkgconfig files with absolute paths
# Rewrite if so
def fixup_generated_pkgconfig_files():
	for root, dirs, files in os.walk(os.environ['DISTDIR']):
		if os.path.basename(root) == 'pkgconfig':
			for f in files:
				if f.endswith('.pc'):
					info("Checking generated pkgconfig file '%s'", f)
					fixup_generated_pkgconfig_file(os.path.join(root, f))

def remove_la_file(path):
	# Read the contents...
	stream = open(path)
	data = stream.read()
	stream.close()

	# Check it really is a libtool archive...
	if 'Please DO NOT delete this file' not in data:
		warn("Ignoring %s; doesn't look like a libtool archive", path)
		return

	os.unlink(path)
	print "Removed %s (.la files contain absolute paths)" % path

# libtool archives contain hard-coded paths. Lucky, modern systems don't need them, so remove
# them.
def remove_la_files():
	for root, dirs, files in os.walk(os.environ['DISTDIR']):
		if os.path.basename(root) == 'lib':
			for f in files:
				if f.endswith('.la'):
					remove_la_file(os.path.join(root, f))
				if f.endswith('.a'):
					warn("Found static archive '%s'; maybe build with --disable-static?", f)

class CompileSetup(run.Setup):
	def do_binding(self, impl, b, iface):
		if isinstance(b, model.EnvironmentBinding):
			if b.name == 'PKG_CONFIG_PATH':
				do_pkg_config_binding(b, impl)
			else:
				do_env_binding(b, lookup(impl))
		else:
			run.Setup.do_binding(self, impl, b, iface)

def do_build_internal(options, args):
	"""build-internal"""
	# If a sandbox is being used, we're in it now.
	import getpass, socket

	buildenv = BuildEnv()
	sels = buildenv.get_selections()

	builddir = os.path.realpath('build')
	ensure_dir(buildenv.metadir)

	build_env_xml = join(buildenv.metadir, 'build-environment.xml')

	buildenv_doc = sels.toDOM()

	# Create build-environment.xml file
	root = buildenv_doc.documentElement
	info = buildenv_doc.createElementNS(XMLNS_0COMPILE, 'build-info')
	root.appendChild(info)
	info.setAttributeNS(None, 'time', time.strftime('%Y-%m-%d %H:%M').strip())
	info.setAttributeNS(None, 'host', socket.getfqdn())
	info.setAttributeNS(None, 'user', getpass.getuser())
	info.setAttributeNS(None, 'arch', '%s-%s' % (uname[0], uname[4]))
	stream = file(build_env_xml, 'w')
	buildenv_doc.writexml(stream, addindent="  ", newl="\n")
	stream.close()

	# Create local binary interface file.
	# We use the main feed for the interface as the template for the name,
	# summary, etc (note: this is not necessarily the feed that contained
	# the source code).
	master_feed = iface_cache.get_feed(buildenv.interface)
	src_impl = buildenv.chosen_impl(buildenv.interface)
	write_sample_feed(buildenv, master_feed, src_impl)

	# Check 0compile is new enough
	min_version = model.parse_version(src_impl.attrs.get(XMLNS_0COMPILE + ' min-version', None))
	if min_version and min_version > model.parse_version(__main__.version):
		raise SafeException("%s-%s requires 0compile >= %s, but we are only version %s" %
				(master_feed.get_name(), src_impl.version, model.format_version(min_version), __main__.version))

	# Create the patch
	patch_file = join(buildenv.metadir, 'from-%s.patch' % src_impl.version)
	if buildenv.user_srcdir:
		with open(patch_file, 'w') as stream:
			# (ignore errors; will already be shown on stderr)
			try:
				subprocess.call(["diff", "-urN", buildenv.orig_srcdir, 'src'], stdout = stream)
			except OSError as ex:
				print >>sys.stderr, "WARNING: Failed to run 'diff': ", ex
		if os.path.getsize(patch_file) == 0:
			os.unlink(patch_file)
	elif os.path.exists(patch_file):
		os.unlink(patch_file)

	env('BUILDDIR', builddir)
	env('DISTDIR', buildenv.distdir)
	env('SRCDIR', buildenv.user_srcdir or buildenv.orig_srcdir)
	env('BINARYFEED', buildenv.local_iface_file)
	os.chdir(builddir)
	print "cd", builddir

	setup = CompileSetup(iface_cache.stores, sels)
	setup.prepare_env()

	# These mappings are needed when mixing Zero Install -dev packages with
	# native package binaries.
	mappings = {}
	for impl in sels.selections.values():
		# Add mappings that have been set explicitly...
		new_mappings = impl.attrs.get(XMLNS_0COMPILE + ' lib-mappings', '')
		if new_mappings:
			new_mappings = new_mappings.split(' ')
			for mapping in new_mappings:
				assert ':' in mapping, "lib-mappings missing ':' in '%s' from '%s'" % (mapping, impl.feed)
				name, major_version = mapping.split(':', 1)
				assert '/' not in mapping, "lib-mappings '%s' contains a / in the version number (from '%s')!" % (mapping, impl.feed)
				if sys.platform == 'darwin':
					mappings[name] = 'lib%s.%s.dylib' % (name, major_version)
				else:
					mappings[name] = 'lib%s.so.%s' % (name, major_version)
		# Auto-detect required mappings where possible...
		# (if the -dev package is native, the symlinks will be OK)
		if not is_package_impl(impl):
			impl_path = lookup(impl)
			for libdirname in ['lib', 'usr/lib', 'lib64', 'usr/lib64']:
				libdir = os.path.join(impl_path, libdirname)
				if os.path.isdir(libdir):
					find_broken_version_symlinks(libdir, mappings)

	if mappings:
		set_up_mappings(mappings)

	overrides_dir = os.path.join(os.environ['TMPDIR'], PKG_CONFIG_OVERRIDES)
	if os.path.isdir(overrides_dir):
		add_overrides = model.EnvironmentBinding('PKG_CONFIG_PATH', PKG_CONFIG_OVERRIDES)
		do_env_binding(add_overrides, os.environ['TMPDIR'])

	# Some programs want to put temporary build files in the source directory.
	# Make a copy of the source if needed.
	dup_src_type = src_impl.attrs.get(XMLNS_0COMPILE + ' dup-src', None)
	if dup_src_type == 'true':
		dup_src(shutil.copy2)
		env('SRCDIR', builddir)
	elif dup_src_type:
		raise Exception("Unknown dup-src value '%s'" % dup_src_type)

	if options.shell:
		spawn_and_check(find_in_path('cmd' if os.name == 'nt' else 'sh'), [])
	else:
		command = sels.commands[0].qdom.attrs.get('shell-command', None)
		if command is None:
			# New style <command>
			prog_args = setup.build_command(sels.interface, sels.command) + args
		else:
			# Old style shell-command='...'
			if os.name == 'nt':
				prog_args = [os.environ['0COMPILE_BASH'], '-eux', '-c', command] + args
			else:
				prog_args = ['/bin/sh', '-c', command + ' "$@"', '-'] + args
			assert len(sels.commands) == 1

		# Remove any existing log files
		for log in ['build.log', 'build-success.log', 'build-failure.log']:
			if os.path.exists(log):
				os.unlink(log)

		# Run the command, copying output to a new log
		with open('build.log', 'w') as log:
			print >>log, "Build log for %s-%s" % (master_feed.get_name(),
							      src_impl.version)
			print >>log, "\nBuilt using 0compile-%s" % __main__.version
			print >>log, "\nBuild system: " + ', '.join(uname)
			print >>log, "\n%s:\n" % ENV_FILE
			with open(os.path.join(os.pardir, ENV_FILE)) as properties_file:
				shutil.copyfileobj(properties_file, log)

			log.write('\n')

			if os.path.exists(patch_file):
				print >>log, "\nPatched with:\n"
				shutil.copyfileobj(file(patch_file), log)
				log.write('\n')

			if command:
				print "Executing: " + command, args
				print >>log, "Executing: " + command, args
			else:
				print "Executing: " + str(prog_args)
				print >>log, "Executing: " + str(prog_args)

			# Tee the output to the console and to the log
			child = subprocess.Popen(prog_args, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
			while True:
				data = os.read(child.stdout.fileno(), 100)
				if not data: break
				sys.stdout.write(data)
				log.write(data)
			status = child.wait()
			failure = None
			if status == 0:
				print >>log, "Build successful"
				shorten_dynamic_library_install_names()
				fixup_generated_pkgconfig_files()
				remove_la_files()
			elif status > 0:
				failure = "Build failed with exit code %d" % status
			else:
				failure = "Build failure: exited due to signal %d" % (-status)
			if failure:
				print >>log, failure

		if failure:
			os.rename('build.log', 'build-failure.log')
			raise SafeException("Command '%s': %s" % (prog_args, failure))
		else:
			os.rename('build.log', 'build-success.log')

def do_build(args):
	"""build [ --no-sandbox ] [ --shell | --force | --clean ]"""
	buildenv = BuildEnv()
	sels = buildenv.get_selections()

	parser = OptionParser(usage="usage: %prog build [options]")

	parser.add_option('', "--no-sandbox", help="disable use of sandboxing", action='store_true')
	parser.add_option("-s", "--shell", help="run a shell instead of building", action='store_true')
	parser.add_option("-c", "--clean", help="remove the build directories", action='store_true')
	parser.add_option("-f", "--force", help="build even if dependencies have changed", action='store_true')

	parser.disable_interspersed_args()

	(options, args2) = parser.parse_args(args)

	builddir = os.path.realpath('build')

	changes = buildenv.get_build_changes()
	if changes:
		if not (options.force or options.clean):
			raise SafeException("Build dependencies have changed:\n" +
					'\n'.join(changes) + "\n\n" +
					"To build anyway, use: 0compile build --force\n" +
					"To do a clean build:  0compile build --clean")
		if not options.no_sandbox:
			print "Build dependencies have changed:\n" + '\n'.join(changes)

	ensure_dir(builddir, options.clean)
	ensure_dir(buildenv.distdir, options.clean)

	if options.no_sandbox:
		return do_build_internal(options, args2)

	tmpdir = tempfile.mkdtemp(prefix = '0compile-')
	try:
		my_dir = os.path.dirname(__file__)
		readable = ['.', my_dir]
		writable = ['build', buildenv.distdir, tmpdir]
		env('TMPDIR', tmpdir)

		for selection in sels.selections.values():
			if not is_package_impl(selection):
				readable.append(lookup(selection))

		options = []
		if __main__.options.verbose:
			options.append('--verbose')

		readable.append('/etc')	# /etc/ld.*

		spawn_and_check_maybe_sandboxed(readable, writable, tmpdir, sys.executable, ['-u', sys.argv[0]] + options + ['build', '--no-sandbox'] + args)
	finally:
		info("Deleting temporary directory '%s'" % tmpdir)
		shutil.rmtree(tmpdir)

def find_feed_for(master_feed):
	"""Determine the <feed-for> interface for the new binary's feed.
	remote feed (http://...) => the binary is a feed for the interface with this URI
	local feed (/feed.xml) => copy <feed-for> from feed.xml (e.g. for a Git clone)
	local copy of remote feed (no feed-for) => feed's uri attribute
	"""
	if hasattr(master_feed, 'local_path'):
		is_local = master_feed.local_path is not None		# 0install >= 1.7
	else:
		is_local = os.path.isabs(master_feed.url)

	uri = master_feed.url

	if is_local:
		print "Note: source %s is a local feed" % uri
		for feed_uri in master_feed.feed_for or []:
			uri = feed_uri
			print "Will use <feed-for interface='%s'> instead..." % uri
			break
		else:
			master_feed = minidom.parse(uri).documentElement
			if master_feed.hasAttribute('uri'):
				uri = master_feed.getAttribute('uri')
				print "Will use <feed-for interface='%s'> instead..." % uri

	return uri

def write_sample_feed(buildenv, master_feed, src_impl):
	path = buildenv.local_iface_file

	old_path = os.path.join(buildenv.metadir, buildenv.iface_name + '.xml')
	if os.path.exists(old_path):
		warn("Removing old %s file: use %s instead now", old_path, path)
		os.unlink(old_path)

	impl = minidom.getDOMImplementation()

	XMLNS_IFACE = namespaces.XMLNS_IFACE

	doc = impl.createDocument(XMLNS_IFACE, "interface", None)

	root = doc.documentElement
	root.setAttributeNS(XMLNS_NAMESPACE, 'xmlns', XMLNS_IFACE)
	prefixes = Prefixes(XMLNS_IFACE)

	def addSimple(parent, name, text = None):
		elem = doc.createElementNS(XMLNS_IFACE, name)

		parent.appendChild(doc.createTextNode('\n' + '  ' * (1 + depth(parent))))
		parent.appendChild(elem)
		if text:
			elem.appendChild(doc.createTextNode(text))
		return elem

	def close(element):
		element.appendChild(doc.createTextNode('\n' + '  ' * depth(element)))

	addSimple(root, 'name', master_feed.name)
	addSimple(root, 'summary', master_feed.summary)
	addSimple(root, 'description', master_feed.description)
	feed_for = addSimple(root, 'feed-for')

	feed_for.setAttributeNS(None, 'interface', find_feed_for(master_feed))

	group = addSimple(root, 'group')
	main = src_impl.attrs.get(XMLNS_0COMPILE + ' binary-main', None)
	if main:
		group.setAttributeNS(None, 'main', main)

	lib_mappings = src_impl.attrs.get(XMLNS_0COMPILE + ' binary-lib-mappings', None)
	if lib_mappings:
		prefixes.setAttributeNS(group, XMLNS_0COMPILE, 'lib-mappings', lib_mappings)
	
	for d in src_impl.dependencies:
		if parse_bool(d.metadata.get(XMLNS_0COMPILE + ' include-binary', 'false')):
			requires = d.qdom.toDOM(doc, prefixes)
			requires.removeAttributeNS(XMLNS_0COMPILE, 'include-binary')
			group.appendChild(requires)
	set_arch = True

	impl_elem = addSimple(group, 'implementation')
	impl_template = buildenv.get_binary_template()
	if impl_template:
		# Copy attributes from template
		for fullname, value in impl_template.attrs.iteritems():
			if fullname == 'arch':
				set_arch = False
				if value == '*-*':
					continue
			if ' ' in fullname:
				ns, localName = fullname.split(' ', 1)
			else:
				ns, localName = None, fullname
			prefixes.setAttributeNS(impl_elem, ns, localName, value)
		# Copy child nodes
		for child in impl_template.childNodes:
			impl_elem.appendChild(child.toDOM(doc, prefixes))
		if impl_template.content:
			impl_elem.appendChild(doc.createTextNode(impl_template.content))

	if set_arch:
		group.setAttributeNS(None, 'arch', buildenv.target_arch)

	impl_elem.setAttributeNS(None, 'version', src_impl.version)

	version_modifier = buildenv.version_modifier
	if version_modifier:
		impl_elem.setAttributeNS(None, 'version-modifier', version_modifier)

	impl_elem.setAttributeNS(None, 'id', '..')
	impl_elem.setAttributeNS(None, 'released', time.strftime('%Y-%m-%d'))
	close(group)
	close(root)

	for ns, prefix in prefixes.prefixes.items():
		root.setAttributeNS(XMLNS_NAMESPACE, 'xmlns:' + prefix, ns)

	stream = codecs.open(path, 'w', encoding = 'utf-8')
	try:
		doc.writexml(stream)
	finally:
		stream.close()

def find_broken_version_symlinks(libdir, mappings):
	"""libdir may be a legacy -devel package containing lib* symlinks whose
	targets would be provided by the corresponding runtime package. If so,
	create fixed symlinks under $TMPDIR with the real location."""
	prefix = 'lib'
	if sys.platform == 'darwin':
		extension = '.dylib'
	else:
		extension = '.so'

	for x in os.listdir(libdir):
		if x.startswith(prefix) and x.endswith(extension):
			path = os.path.join(libdir, x)
			if os.path.islink(path):
				target = os.readlink(path)
				if '/' not in target and not os.path.exists(os.path.join(libdir, target)):
					print "Broken link %s -> %s; will relocate..." % (x, target)
					mappings[x[len(prefix):-len(extension)]] = target

def set_up_mappings(mappings):
	"""Create a temporary directory with symlinks for each of the library mappings."""
	libdirs = []
	if sys.platform == 'darwin':
		LD_LIBRARY_PATH='DYLD_LIBRARY_PATH'
	else:
		LD_LIBRARY_PATH='LD_LIBRARY_PATH'
	for d in os.environ.get(LD_LIBRARY_PATH, '').split(':'):
		if d: libdirs.append(d)
	libdirs += ['/lib', '/usr/lib']

	def add_ldconf(config_file):
		if not os.path.isfile(config_file):
			return
		for line in file(config_file):
			d = line.strip()
			if d.startswith('include '):
				glob_pattern = d.split(' ', 1)[1]
				for conf in glob.glob(glob_pattern):
					add_ldconf(conf)
			elif d and not d.startswith('#'):
				libdirs.append(d)
	add_ldconf('/etc/ld.so.conf')

	def find_library(name, wanted):
		# Takes a short-name and target name of a library and returns
		# the full path of the library.
		for d in libdirs:
			path = os.path.join(d, wanted)
			if os.path.exists(path):
				return path
		print "WARNING: library '%s' not found (searched '%s')!" % (wanted, libdirs)
		return None

	mappings_dir = os.path.join(os.environ['TMPDIR'], 'lib-mappings')
	os.mkdir(mappings_dir)

	old_path = os.environ.get('LIBRARY_PATH', '')
	if old_path: old_path = ':' + old_path
	os.environ['LIBRARY_PATH'] = mappings_dir + old_path

	if sys.platform == 'darwin':
		soext='.dylib'
	else:
		soext='.so'
	for name, wanted in mappings.items():
		target = find_library(name, wanted)
		if target:
			print "Adding mapping lib%s%s -> %s" % (name, soext, target)
			os.symlink(target, os.path.join(mappings_dir, 'lib' + name + soext))

def dup_src(fn):
	srcdir = os.path.join(os.environ['SRCDIR'], '')
	builddir = os.environ['BUILDDIR']

	build_in_src = srcdir + 'build' == builddir

	for root, dirs, files in os.walk(srcdir):
		assert root.startswith(srcdir)
		reldir = root[len(srcdir):]

		if reldir == '.git' or (reldir == 'build' and build_in_src):
			print "dup-src: skipping", reldir
			dirs[:] = []
			continue

		for f in files:
			target = os.path.join(reldir, f)
			#print "Copy %s -> %s" % (os.path.join(root, f), target)
			if os.path.exists(target):
				os.unlink(target)
			fn(os.path.join(root, f), target)
		for d in dirs:
			target = os.path.join(reldir, d)
			if not os.path.isdir(target):
				os.mkdir(target)

__main__.commands.append(do_build)
