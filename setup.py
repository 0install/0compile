# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import os, sys, __main__

from zeroinstall.injector import model, namespaces, qdom
from zeroinstall import SafeException

from support import BuildEnv

def do_setup(args, get_dir_callback = None):
	"setup [ SOURCE-URI [ DIR ] ]"
	if len(args) == 0:
		assert get_dir_callback is None
		buildenv = BuildEnv()
		interface = buildenv.interface
		assert interface
		create_dir = None
		buildenv.get_selections(prompt = True)
	else:
		buildenv = BuildEnv(need_config = False)
		interface = args[0]
		if get_dir_callback:
			assert len(args) == 1
		if len(args) == 1:
			create_dir = os.path.basename(interface)
			if create_dir.endswith('.xml'):
				create_dir = create_dir[:-4]
			if create_dir.startswith('alias:'):
				create_dir = create_dir.split(':', 1)[1]
			assert os.path.dirname(create_dir) == ''
			assert create_dir != os.path.curdir
			if get_dir_callback:
				create_dir = get_dir_callback(create_dir)
		elif len(args) == 2:
			create_dir = args[1]
			if create_dir == '.':
				create_dir = None
		else:
			raise __main__.UsageError()

		iface_uri = model.canonical_iface_uri(args[0])
		if os.path.isabs(iface_uri):
			# Use a relative path if the feed is inside the current directory.
			# This is useful if the properties file is shared with other users.
			rel_iface_uri = os.path.relpath(iface_uri, create_dir or ".")
			if not rel_iface_uri.startswith("."):
				iface_uri = rel_iface_uri

			with open(iface_uri, 'rb') as stream:
				root = qdom.parse(stream)
			if root.uri == namespaces.XMLNS_IFACE and root.name == 'selections':
				# Looks like this is a selections file, not an interface.
				buildenv.config.set('compile', 'selections', iface_uri)
				iface_uri = root.getAttribute('interface')
		buildenv.config.set('compile', 'interface', iface_uri)

		if create_dir and os.path.exists(create_dir):
			raise SafeException("Directory '%s' already exists." % create_dir)
		buildenv.get_selections()

	if create_dir:
		try:
			os.mkdir(create_dir)
		except:
			print("Failed to create new directory '%s'" % os.path.abspath(create_dir), file=sys.stderr)
			raise
		os.chdir(create_dir)
		print("Created directory %s" % create_dir)

	buildenv.save()

__main__.commands.append(do_setup)
