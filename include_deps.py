# Copyright (C) 2007, Thomas Leonard
# See http://0install.net/0compile.html

import os, __main__
import shutil

from zeroinstall import SafeException
from zeroinstall.zerostore import manifest

from support import BuildEnv, ensure_dir, lookup

def do_include_deps(args):
	"""include-deps"""
	buildenv = BuildEnv()

	depdir = os.path.realpath('dependencies')
	ensure_dir(depdir)

	dirs_to_copy = []

	sels = buildenv.get_selections()
	for needed_iface in sels.selections:
		impl = buildenv.chosen_impl(needed_iface)
		assert impl
		if impl.local_path is not None:
			raise SafeException("Can't export '%s' as it's a local implementation (not supported yet; sorry)" % impl)
		if not impl.id.startswith('package:'):
			dirs_to_copy.append(lookup(impl))
	
	copied = 0
	for cached in dirs_to_copy:
		required_digest = os.path.basename(cached)
		target_impl_dir = os.path.join(depdir, required_digest)
		if not os.path.isdir(target_impl_dir):
			if required_digest.startswith('sha1='):
				shutil.copytree(cached, target_impl_dir)
			else:
				with open(os.path.join(cached, '.manifest'), 'rb') as stream:
					manifest_data = stream.read()
				manifest.copy_tree_with_verify(cached, depdir, manifest_data, required_digest)
			copied += 1

	print("Copied %d dependencies to %s (%d already there)" % (copied, depdir, len(dirs_to_copy) - copied))

__main__.commands.append(do_include_deps)
