# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__
from logging import info
from xml.dom import minidom, XMLNS_NAMESPACE

from zeroinstall.injector import model
from zeroinstall.injector.policy import Policy
from zeroinstall import SafeException

from support import *

def do_setup(args):
	"setup [ SOURCE-URI [ DIR ] ]"
	if len(args) == 0:
		if not os.path.isfile(ENV_FILE):
			raise SafeException("Run 0compile from a directory containing a '%s' file, or "
					    "specify a source URI as an argument." % ENV_FILE)
		doc = get_env_doc()
		interface = doc.documentElement.getAttributeNS(None, 'interface')
		assert interface
	else:
		interface = args[0]
		if len(args) == 1:
			dir = os.path.basename(interface)
			if dir.endswith('.xml'):
				dir = dir[:-4]
			assert '/' not in dir
		elif len(args) == 2:
			dir = args[1]
		else:
			raise __main__.UsageError()

		interface = model.canonical_iface_uri(args[0])

		if os.path.exists(dir):
			raise SafeException("Directory '%s' already exists." % dir)

	# Prompt user to choose versions
	if os.spawnvp(os.P_WAIT, '0launch', ['0launch', '--gui', '--source', '--download-only', interface]):
		raise SafeException('Failed to select source files.')
	
	# Get the chosen versions
	policy = Policy(interface, src = True)
	policy.freshness = 0

	policy.recalculate()
	if not policy.ready:
		raise Exception('Internal error: required source components not found!')

	if len(args) > 0:
		# Create build directory
		if os.path.exists(dir):
			raise SafeException("Directory '%s' already exists." % dir)
		os.mkdir(dir)
		os.chdir(dir)

	# Store choices
	save_environment(policy)

def save_environment(policy):
	impl = minidom.getDOMImplementation()

	doc = impl.createDocument(XMLNS_0COMPILE, "build-environment", None)

	root = doc.documentElement
	root.setAttributeNS(XMLNS_NAMESPACE, 'xmlns', XMLNS_0COMPILE)

	root.setAttributeNS(None, 'interface', policy.root)

	for needed_iface in policy.implementation:
		iface_elem = doc.createElementNS(XMLNS_0COMPILE, 'interface')
		iface_elem.setAttributeNS(None, 'uri', needed_iface.uri)
		root.appendChild(iface_elem)

		impl = policy.implementation[needed_iface]
		assert impl

		impl_elem = doc.createElementNS(XMLNS_0COMPILE, 'implementation')
		impl_elem.setAttributeNS(None, 'id', impl.id)
		impl_elem.setAttributeNS(None, 'version', impl.get_version())
		if impl.interface is not needed_iface:
			impl_elem.setAttributeNS(None, 'from-feed', impl.interface.uri)

		if needed_iface.uri == policy.root:
			command = impl.metadata.get(XMLNS_0COMPILE + ' command', None)
			if not command: raise SafeException("Missing 'compile:command' attribute on <implementation>.")
			impl_elem.setAttributeNS(XMLNS_0COMPILE, 'command', command)
			binary_main = impl.metadata.get(XMLNS_0COMPILE + ' binary-main', None)
			if binary_main:
				impl_elem.setAttributeNS(XMLNS_0COMPILE, 'binary-main', binary_main)

		iface_elem.appendChild(impl_elem)

		for dep in impl.dependencies.values():

			dep_iface = policy.get_interface(dep.interface)
			dep_impl = policy.get_implementation(dep_iface)

			dep_elem = doc.createElementNS(XMLNS_0COMPILE, 'requires')
			dep_elem.setAttributeNS(None, 'interface', dep.interface)
			impl_elem.appendChild(dep_elem)

			for b in dep.bindings:
				if isinstance(b, model.EnvironmentBinding):
					env_elem = doc.createElementNS(XMLNS_0COMPILE, 'environment')
					env_elem.setAttributeNS(None, 'name', b.name)
					env_elem.setAttributeNS(None, 'insert', b.insert)
					if b.default:
						env_elem.setAttributeNS(None, 'default', b.default)
					dep_elem.appendChild(env_elem)
				else:
					raise Exception('Unknown binding type ' + b)

	doc.writexml(file(ENV_FILE, 'w'), addindent = '  ', newl = '\n')

__main__.commands.append(do_setup)
