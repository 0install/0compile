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

def do_setup(args):
	"setup [ SOURCE-URI [ DIR ] ]"
	if len(args) == 0:
		buildenv = BuildEnv()
		interface = buildenv.interface
		assert interface
		create_dir = None
		buildenv.get_selections(prompt = True)
	else:
		buildenv = BuildEnv(need_config = False)
		interface = args[0]
		if len(args) == 1:
			create_dir = os.path.basename(interface)
			if create_dir.endswith('.xml'):
				create_dir = create_dir[:-4]
			assert '/' not in create_dir
			assert create_dir is not '.'
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

	setup(buildenv, create_dir)

def setup(buildenv, create_dir):
	if create_dir:
		if os.path.exists(create_dir):
			raise SafeException("Directory '%s' already exists." % create_dir)
		os.mkdir(create_dir)
		os.chdir(create_dir)
		print "Created directory %s" % create_dir

	buildenv.save()

def save_environment(sels):
	download_base = None
	if os.path.exists(ENV_FILE):
		# Don't lose existing download URL
		download_base = BuildEnv().download_base_url

	doc = sels.toDOM()
	root = doc.documentElement

	root.setAttributeNS(XMLNS_NAMESPACE, 'xmlns:compile', XMLNS_0COMPILE)

	if download_base:
		root.setAttributeNS(XMLNS_0COMPILE, 'compile:download-base-url', download_base)

	impl = sels.selections[sels.interface]
	command = impl.attrs.get(XMLNS_0COMPILE + ' command', None)
	if not command: raise SafeException("Missing 'compile:command' attribute on <implementation>.")
	root.setAttributeNS(XMLNS_0COMPILE, 'compile:command', command)

	for name in ['binary-main', 'binary-lib-mappings', 'metadir', 'dup-src']:
		value = impl.attrs.get(XMLNS_0COMPILE + ' ' + name, None)
		if value:
			root.setAttributeNS(XMLNS_0COMPILE, 'compile:' + name, value)

	doc.writexml(file(ENV_FILE, 'w'), addindent = '  ', newl = '\n')

__main__.commands.append(do_setup)
