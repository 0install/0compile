# Copyright (C) 2009, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__, tempfile

from zeroinstall import SafeException
from zeroinstall.injector import arch, handler, policy, model, iface_cache
from zeroinstall.support import tasks

from support import BuildEnv

# This is a bit hacky...
#
# We invent a new CPU type which is compatible with the host but worse than
# every existing type, and we use * for the OS type so that we don't beat 'Any'
# binaries either. This means that we always prefer an existing binary of the
# desired version to compiling a new one, but we'll compile a new version from source
# rather than use an older binary.
arch.machine_groups['newbuild'] = arch.machine_groups.get(arch._uname[-1], 0)
arch.machine_ranks['newbuild'] = max(arch.machine_ranks.values()) + 1
host_arch = '*-newbuild'

# 0launch 0.40 not released yet, so include a copy here
class VersionRestriction(model.Restriction):
	"""Only select implementations with a particular version number."""

	def __init__(self, version):
		"""@param version: the required version number
		@see: L{parse_version}; use this to pre-process the version number
		"""
		self.version = version

	def meets_restriction(self, impl):
		return impl.version == self.version

	def __str__(self):
		return "(restriction: version = %s)" % model.format_version(self.version)

class AutocompileCache(iface_cache.IfaceCache):
	def __init__(self):
		iface_cache.IfaceCache.__init__(self)
		self.done = set()

	def get_interface(self, uri):
		iface = iface_cache.IfaceCache.get_interface(self, uri)
		if not iface: return None
		feed = iface._main_feed

		# Note: when a feed is updated, a new ZeroInstallFeed object is created,
		# so record whether we've seen the feed, not the interface.

		if feed not in self.done:
			self.done.add(feed)

			# For each source impl, add a corresponding binary
			# (the binary has no dependencies as we can't predict them here,
			# but they're not the same as the source's dependencies)

			srcs = [x for x in feed.implementations.itervalues() if x.arch and x.arch.endswith('-src')]
			for x in srcs:
				new_id = '0compile=' + x.id
				if not new_id in feed.implementations:
					new = feed._get_impl(new_id)
					new.set_arch(host_arch)
					new.version = x.version

		return iface

policy.iface_cache = AutocompileCache()

def pretty_print_plan(solver, root, indent = '- '):
	"""Display a tree showing the selected implementations."""
	iface = solver.iface_cache.get_interface(root)
	impl = solver.selections[iface]
	if impl is None:
		msg = 'Failed to select any suitable version (source or binary)'
	elif impl.id.startswith('0compile='):
		real_impl_id = impl.id.split('=', 1)[1]
		real_impl = impl.feed.implementations[real_impl_id]
		msg = 'Compile %s (%s)' % (real_impl.get_version(), real_impl.id)
	elif impl.arch and impl.arch.endswith('-src'):
		msg = 'Compile %s (%s)' % (impl.get_version(), impl.id)
	else:
		if impl.arch:
			msg = 'Use existing binary %s (%s)' % (impl.get_version(), impl.arch)
		else:
			msg = 'Use existing architecture-independent package %s' % impl.get_version()
	print "%s%s: %s" % (indent, iface.get_name(), msg)

	if impl:
		indent = '  ' + indent
		for x in impl.requires:
			pretty_print_plan(solver, x.interface, indent)

def print_details(solver):
	"""Dump debugging details."""
	print "\nDetails of all components and versions considered:"
	for iface in solver.details:
		print '\n%s\n' % iface.get_name()
		for impl, note in solver.details[iface]:
			print '%s (%s) : %s' % (impl.get_version(), impl.arch or '*-*', note or 'OK')
	print "\nEnd details"

def do_autocompile(args):
	"""autocompile URI"""
	if len(args) != 1:
		raise __main__.UsageError()
	iface_uri = model.canonical_iface_uri(args[0])

	h = handler.Handler()

	@tasks.async
	def recursive_build(iface_uri, version = None):
		p = policy.Policy(iface_uri, handler = h, src = True)
		iface = p.solver.iface_cache.get_interface(iface_uri)
		p.solver.record_details = True
		if version:
			p.solver.extra_restrictions[iface] = [VersionRestriction(model.parse_version(version))]

		# For testing...
		#p.target_arch = arch.Architecture(os_ranks = {'FreeBSD': 0, None: 1}, machine_ranks = {'i386': 0, None: 1, 'newbuild': 2})

		print (' %s ' % iface_uri).center(76, '=')
		print "\nSelecting versions..."
		solved = p.solve_with_downloads()
		if solved:
			yield solved
			tasks.check(solved)

		if not p.solver.ready:
			print_details(p.solver)
			raise SafeException("Can't find all required implementations (source or binary):\n" +
				'\n'.join(["- %s -> %s" % (iface, p.solver.selections[iface])
					   for iface in p.solver.selections]))
		print "Selection done."

		print "\nPlan:\n"
		pretty_print_plan(p.solver, p.root)

		for iface, impl in p.solver.selections.iteritems():
			if impl.id.startswith('0compile='):
				print
				build = recursive_build(iface.uri, impl.get_version())
				yield build
				tasks.check(build)

	h.wait_for_blocker(recursive_build(iface_uri))

__main__.commands += [do_autocompile]
