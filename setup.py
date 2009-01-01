# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__
from logging import info
from xml.dom import minidom, XMLNS_NAMESPACE

from zeroinstall.injector import model, selections, namespaces
from zeroinstall.injector.handler import Handler
from zeroinstall.injector.iface_cache import iface_cache
from zeroinstall.injector.policy import Policy
from zeroinstall import SafeException, helpers

from support import *

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
			assert '/' not in create_dir
			assert create_dir is not '.'
			if get_dir_callback:
				create_dir = get_dir_callback(create_dir)
		elif len(args) == 2:
			create_dir = args[1]
			if create_dir == '.':
				create_dir = None
		else:
			raise __main__.UsageError()

		iface_uri = model.canonical_iface_uri(args[0])
		if iface_uri.startswith('/'):
			root = qdom.parse(file(iface_uri))
			if root.uri == namespaces.XMLNS_IFACE and root.name == 'selections':
				# Looks like this is a selections file, not an interface.
				buildenv.config.set('compile', 'selections', iface_uri)
				iface_uri = root.getAttribute('interface')
		buildenv.config.set('compile', 'interface', iface_uri)

		if create_dir and os.path.exists(create_dir):
			raise SafeException("Directory '%s' already exists." % create_dir)
		buildenv.get_selections()

	if create_dir:
		os.mkdir(create_dir)
		os.chdir(create_dir)
		print "Created directory %s" % create_dir

	buildenv.save()

__main__.commands.append(do_setup)
