# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__
from logging import info
from xml.dom import minidom, XMLNS_NAMESPACE

from zeroinstall.injector import model, selections
from zeroinstall.injector.iface_cache import iface_cache
from zeroinstall.injector.policy import Policy
from zeroinstall import SafeException

from support import *

def do_setup(args):
	"setup [--no-prompt] [ SOURCE-URI [ DIR ] ]"
	prompt = True
	if args and args[0] == '--no-prompt':
		del args[0]
		prompt = False

	if len(args) == 0:
		if not os.path.isfile(ENV_FILE):
			raise SafeException("Run 0compile from a directory containing a '%s' file, or "
					    "specify a source URI as an argument." % ENV_FILE)
		
		buildenv = BuildEnv()
		interface = buildenv.interface
		assert interface
		create_dir = None
	else:
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

		interface = model.canonical_iface_uri(args[0])

		if create_dir and os.path.exists(create_dir):
			raise SafeException("Directory '%s' already exists." % create_dir)
	
	setup(interface, create_dir, prompt)

def setup(interface, create_dir, prompt):
	if prompt:
		gui_options = '--gui'
	else:
		gui_options = '--offline'

	# Prompt user to choose versions
	if os.spawnvp(os.P_WAIT, '0launch', ['0launch', gui_options, '--source', '--download-only', interface]):
		raise SafeException('Failed to select source files.')
	
	# Get the chosen versions
	policy = Policy(interface, src = True)
	policy.freshness = 0

	policy.recalculate()
	if not policy.ready:
		raise Exception('Internal error: required source components not found!')

	root_iface = iface_cache.get_interface(policy.root)
	impl = policy.implementation[root_iface]
	min_version = parse_version(impl.metadata.get(XMLNS_0COMPILE + ' min-version', None))
	if min_version and min_version > parse_version(__main__.version):
		raise SafeException("%s-%s requires 0compile >= %s, but we are only version %s" %
				(root_iface.get_name(), impl.get_version(), format_version(min_version), __main__.version))

	if create_dir:
		if os.path.exists(create_dir):
			raise SafeException("Directory '%s' already exists." % create_dir)
		os.mkdir(create_dir)
		os.chdir(create_dir)

	# Store choices
	save_environment(policy)

def save_environment(policy):
	download_base = None
	if os.path.exists(ENV_FILE):
		# Don't lose existing download URL
		download_base = BuildEnv().download_base_url

	sels = selections.Selections(policy)

	# Copy mappings metadata
	for iface, impl in policy.implementation.iteritems():
		mappings = impl.metadata.get(XMLNS_0COMPILE + ' lib-mappings', None)
		if mappings:
			sels.selections[iface.uri].attrs[XMLNS_0COMPILE + ' lib-mappings'] = mappings

	doc = sels.toDOM()
	root = doc.documentElement

	root.setAttributeNS(XMLNS_NAMESPACE, 'xmlns:compile', XMLNS_0COMPILE)

	if download_base:
		root.setAttributeNS(XMLNS_0COMPILE, 'compile:download-base-url', download_base)

	impl = policy.implementation[iface_cache.get_interface(policy.root)]
	command = impl.metadata.get(XMLNS_0COMPILE + ' command', None)
	if not command: raise SafeException("Missing 'compile:command' attribute on <implementation>.")
	root.setAttributeNS(XMLNS_0COMPILE, 'compile:command', command)

	for name in ['binary-main', 'binary-lib-mappings', 'metadir']:
		value = impl.metadata.get(XMLNS_0COMPILE + ' ' + name, None)
		if value:
			root.setAttributeNS(XMLNS_0COMPILE, 'compile:' + name, value)

	doc.writexml(file(ENV_FILE, 'w'), addindent = '  ', newl = '\n')

__main__.commands.append(do_setup)
