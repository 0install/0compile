# Copyright (C) 2006, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import sys, os, __main__

def do_build(args):
	"""build"""
	#build_dir = os.path.expanduser('~/0compile-builds')
	#ensure_dir(build_dir)

	def env(name, value):
		info('Setting %s="%s"', name, value)
		os.environ[name] = value

	if os.spawnvp(os.P_WAIT, '0launch', ['0launch', '--source', '--download-only', interface]):
		raise Exception('Failed to download source files')
	
	policy = Policy(interface, src = True)
	policy.freshness = 0

	policy.recalculate()
	if not policy.ready:
		raise Exception('Internal error: required source components not found!')
	iface = policy.get_interface(interface)
	impl = policy.get_implementation(iface)
	main = impl.main
	if main is None:
		raise SafeException("Missing 'main' attribute in source implementation '%s'" % impl)
	assert not main.startswith('/')
	main = os.path.join(policy.get_implementation_path(impl), main)
	srcdir = os.path.dirname(main)

	distdir = os.path.realpath('dist')
	builddir = os.path.realpath('build')

	ensure_dir(builddir)
	ensure_dir(distdir)

	tmpdir = tempfile.mkdtemp(prefix = '0compile-')
	try:
		env('TMPDIR', tmpdir)
		env('BUILDDIR', builddir)
		env('DISTDIR', distdir)
		env('SRCDIR', srcdir)
		os.chdir(builddir)

		spawn(policy, None, args)
	finally:
		info("Deleting temporary directory '%s'" % tmpdir)
		shutil.rmtree(tmpdir)

__main__.commands.append(do_build)
