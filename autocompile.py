# Copyright (C) 2009, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__, tempfile, subprocess, signal, shutil
from xml.dom import minidom
from optparse import OptionParser
from logging import warn

from zeroinstall import SafeException
from zeroinstall.injector import arch, handler, driver, requirements, model, iface_cache, namespaces, writer, reader, qdom
from zeroinstall.injector.config import load_config
from zeroinstall.zerostore import manifest, NotStored
from zeroinstall.support import tasks, basedir, ro_rmtree

from support import BuildEnv, canonicalize_machine, XMLNS_0COMPILE
import support

build_target_machine_type = canonicalize_machine(support.uname[4])
assert build_target_machine_type in arch.machine_ranks, "Build target machine type '{build_target_machine_type}' is not supported on this platform; expected one of {types}".format(
		build_target_machine_type = build_target_machine_type,
		types = list(arch.machine_ranks.keys()))

# This is a bit hacky...
#
# We invent a new CPU type which is compatible with the host but worse than
# every existing type, and we use * for the OS type so that we don't beat 'Any'
# binaries either. This means that we always prefer an existing binary of the
# desired version to compiling a new one, but we'll compile a new version from source
# rather than use an older binary.
arch.machine_groups['newbuild'] = arch.machine_groups.get(build_target_machine_type, 0)
arch.machine_ranks['newbuild'] = max(arch.machine_ranks.values()) + 1
host_arch = '*-newbuild'

class ImplRestriction(model.Restriction):
	reason = "Not the source we're trying to build"

	def __init__(self, impl_id):
		self.impl_id = impl_id

	def meets_restriction(self, impl):
		return impl.id == self.impl_id

	def __str__(self):
		return _("implementation {impl}").format(impl = self.impl_id)

class NewBuildImplementation(model.ZeroInstallImplementation):
	# Assume that this (potential) binary is available so that we can select it as a
	# dependency.
	def is_available(self, stores):
		return True

def get_commands(src_impl):
	"""Estimate the commands that the generated binary would have."""
	cmd = src_impl.commands.get('compile', None)
	if cmd is None:
		warn("Source has no compile command! %s", src_impl)
		return []

	for elem in cmd.qdom.childNodes:
		if elem.uri == XMLNS_0COMPILE and elem.name == 'implementation':
			# Assume there's always a run command. Doesn't do any harm to have extra ones,
			# and there are various ways this might get created.
			commands = ['run']
			for e in elem.childNodes:
				if e.uri == namespaces.XMLNS_IFACE and e.name == 'command':
					commands.append(e.getAttribute('name'))
			return commands
	return []

def add_binary_deps(src_impl, binary_impl):
	# If src_impl contains a template, add those dependencies to the potential binary.
	# Note: probably we should add "include-binary" dependencies here too...

	compile_command = src_impl.commands['compile']

	for elem in compile_command.qdom.childNodes:
		if elem.uri == XMLNS_0COMPILE and elem.name == 'implementation':
			template = elem
			break
	else:
		return	# No template

	for elem in template.childNodes:
		if elem.uri == namespaces.XMLNS_IFACE and elem.name in ('requires', 'restricts', 'runner'):
			dep = model.process_depends(elem, local_feed_dir = None)
			binary_impl.requires.append(dep)

class AutocompileCache(iface_cache.IfaceCache):
	def __init__(self):
		iface_cache.IfaceCache.__init__(self)
		self.done = set()

	def get_feed(self, url, force = False):
		feed = iface_cache.IfaceCache.get_feed(self, url, force)
		if not feed: return None

		if feed not in self.done:
			self.done.add(feed)

			# For each source impl, add a corresponding binary
			# (the binary has no dependencies as we can't predict them here,
			# but they're not the same as the source's dependencies)

			srcs = [x for x in feed.implementations.itervalues() if x.arch and x.arch.endswith('-src')]
			for x in srcs:
				new_id = '0compile=' + x.id
				if not new_id in feed.implementations:
					new = NewBuildImplementation(feed, new_id, None)
					feed.implementations[new_id] = new
					new.set_arch(host_arch)
					new.version = x.version

					# Give it some dummy commands in case we're using it as a <runner>, etc (otherwise it can't be selected)
					for cmd_name in get_commands(x):
						cmd = qdom.Element(namespaces.XMLNS_IFACE, 'command', {'path': 'new-build', 'name': cmd_name})
						new.commands[cmd_name] = model.Command(cmd, None)

					# Find the <command name='compile'/>
					add_binary_deps(x, new)

		return feed

class AutoCompiler:
	# If (due to a bug) we get stuck in a loop, we use this to abort with a sensible error.
	seen = None		# ((iface, source_id) -> new_binary_id)

	def __init__(self, config, iface_uri, options):
		self.iface_uri = iface_uri
		self.options = options
		self.config = config

	def pretty_print_plan(self, solver, root, indent = '- '):
		"""Display a tree showing the selected implementations."""
		iface = self.config.iface_cache.get_interface(root)
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
		self.note("%s%s: %s" % (indent, iface.get_name(), msg))

		if impl:
			indent = '  ' + indent
			for x in solver.requires[iface]:
				self.pretty_print_plan(solver, x.interface, indent)

	def print_details(self, solver):
		"""Dump debugging details."""
		self.note("\nFailed. Details of all components and versions considered:")
		for iface in solver.details:
			self.note('\n%s\n' % iface.get_name())
			for impl, note in solver.details[iface]:
				self.note('%s (%s) : %s' % (impl.get_version(), impl.arch or '*-*', note or 'OK'))
		self.note("\nEnd details\n")

	@tasks.aasync
	def compile_and_register(self, sels, forced_iface_uri = None):
		"""If forced_iface_uri, register as an implementation of this interface,
		ignoring the any <feed-for>, etc."""

		buildenv = BuildEnv(need_config = False)
		buildenv.config.set('compile', 'interface', sels.interface)
		buildenv.config.set('compile', 'selections', 'selections.xml')
		
		# Download any required packages now, so we can use the GUI to request confirmation, etc
		download_missing = sels.download_missing(self.config, include_packages = True)
		if download_missing:
			yield download_missing
			tasks.check(download_missing)

		tmpdir = tempfile.mkdtemp(prefix = '0compile-')
		try:
			os.chdir(tmpdir)

			# Write configuration for build...

			buildenv.save()

			sel_file = open('selections.xml', 'w')
			try:
				doc = sels.toDOM()
				doc.writexml(sel_file)
				sel_file.write('\n')
			finally:
				sel_file.close()

			# Do the build...

			build = self.spawn_build(buildenv.iface_name)
			if build:
				yield build
				tasks.check(build)

			# Register the result...
			dom = minidom.parse(buildenv.local_iface_file)

			feed_for_elem, = dom.getElementsByTagNameNS(namespaces.XMLNS_IFACE, 'feed-for')
			claimed_iface = feed_for_elem.getAttribute('interface')

			if forced_iface_uri is not None:
				if forced_iface_uri != claimed_iface:
					self.note("WARNING: registering as feed for {forced}, though feed claims to be for {claimed}".format(
						forced = forced_iface_uri,
						claimed = claimed_iface))
			else:
				forced_iface_uri = claimed_iface		# (the top-level interface being built)

			version = sels.selections[sels.interface].version

			site_package_versions_dir = basedir.save_data_path('0install.net', 'site-packages',
						*model.escape_interface_uri(forced_iface_uri))
			leaf =  '%s-%s' % (version, build_target_machine_type)
			site_package_dir = os.path.join(site_package_versions_dir, leaf)
			self.note("Storing build in %s" % site_package_dir)

			# 1. Copy new version in under a temporary name. Names starting with '.' are ignored by 0install.
			tmp_distdir = os.path.join(site_package_versions_dir, '.new-' + leaf)
			shutil.copytree(buildenv.distdir, tmp_distdir, symlinks = True)

			# 2. Rename the previous build to .old-VERSION (deleting that if it already existed)
			if os.path.exists(site_package_dir):
				self.note("(moving previous build out of the way)")
				previous_build_dir = os.path.join(site_package_versions_dir, '.old-' + leaf)
				if os.path.exists(previous_build_dir):
					shutil.rmtree(previous_build_dir)
				os.rename(site_package_dir, previous_build_dir)
			else:
				previous_build_dir = None

			# 3. Rename the new version immediately after renaming away the old one to minimise time when there's
			# no version.
			os.rename(tmp_distdir, site_package_dir)

			# 4. Delete the old version.
			if previous_build_dir:
				self.note("(deleting previous build)")
				shutil.rmtree(previous_build_dir)

			local_feed = os.path.join(site_package_dir, '0install', 'feed.xml')
			assert os.path.exists(local_feed), "Feed %s not found!" % local_feed

			# Reload - our 0install will detect the new feed automatically
			iface = self.config.iface_cache.get_interface(forced_iface_uri)
			reader.update_from_cache(iface, iface_cache = self.config.iface_cache)
			self.config.iface_cache.get_feed(local_feed, force = True)

			# Write it out - 0install will add the feed so that older 0install versions can find it
			writer.save_interface(iface)

			seen_key = (forced_iface_uri, sels.selections[sels.interface].id)
			assert seen_key not in self.seen, seen_key
			self.seen[seen_key] = site_package_dir
		except:
			self.note("\nBuild failed: leaving build directory %s for inspection...\n" % tmpdir)
			raise
		else:
			# Can't delete current directory on Windows, so move to parent first
			os.chdir(os.path.join(tmpdir, os.path.pardir))

			ro_rmtree(tmpdir)

	@tasks.aasync
	def recursive_build(self, iface_uri, source_impl_id = None):
		"""Build an implementation of iface_uri and register it as a feed.
		@param source_impl_id: the version to build, or None to build any version
		@type source_impl_id: str
		"""
		r = requirements.Requirements(iface_uri)
		r.source = True
		r.command = 'compile'

		d = driver.Driver(self.config, r)
		iface = self.config.iface_cache.get_interface(iface_uri)
		d.solver.record_details = True
		if source_impl_id is not None:
			d.solver.extra_restrictions[iface] = [ImplRestriction(source_impl_id)]

		# For testing...
		#p.target_arch = arch.Architecture(os_ranks = {'FreeBSD': 0, None: 1}, machine_ranks = {'i386': 0, None: 1, 'newbuild': 2})

		while True:
			self.heading(iface_uri)
			self.note("\nSelecting versions for %s..." % iface.get_name())
			solved = d.solve_with_downloads()
			if solved:
				yield solved
				tasks.check(solved)

			if not d.solver.ready:
				self.print_details(d.solver)
				raise d.solver.get_failure_reason()
			self.note("Selection done.")

			self.note("\nPlan:\n")
			self.pretty_print_plan(d.solver, r.interface_uri)
			self.note('')

			needed = []
			for dep_iface_uri, dep_sel in d.solver.selections.selections.iteritems():
				if dep_sel.id.startswith('0compile='):
					if not needed:
						self.note("Build dependencies that need to be compiled first:\n")
					self.note("- {iface} {version}".format(iface = dep_iface_uri, version = dep_sel.version))
					needed.append((dep_iface_uri, dep_sel))

			if not needed:
				self.note("No dependencies need compiling... compile %s itself..." % iface.get_name())
				build = self.compile_and_register(d.solver.selections,
						# force the interface in the recursive case
						iface_uri if iface_uri != self.iface_uri else None)
				yield build
				tasks.check(build)
				return

			# Compile the first missing build dependency...
			dep_iface_uri, dep_sel = needed[0]

			self.note("")

			#details = d.solver.details[self.config.iface_cache.get_interface(dep_iface.uri)]
			#for de in details:
			#	print de

			dep_source_id = dep_sel.id.split('=', 1)[1]
			seen_key = (dep_iface_uri, dep_source_id)
			if seen_key in self.seen:
				self.note_error("BUG: Stuck in an auto-compile loop: already built {key}!".format(key = seen_key))
				# Try to find out why the previous build couldn't be used...
				dep_iface = self.config.iface_cache.get_interface(dep_iface_uri)
				previous_build = self.seen[seen_key]
				previous_build_feed = os.path.join(previous_build, '0install', 'feed.xml')
				previous_feed = self.config.iface_cache.get_feed(previous_build_feed)
				previous_binary_impl = previous_feed.implementations.values()[0]
				raise SafeException("BUG: auto-compile loop: expected to select previously-build binary {binary}:\n\n{reason}".format(
						binary = previous_binary_impl,
						reason = d.solver.justify_decision(r, dep_iface, previous_binary_impl)))

			build = self.recursive_build(dep_iface_uri, dep_source_id)
			yield build
			tasks.check(build)

			assert seen_key in self.seen, (seen_key, self.seen)	# Must have been built by now

			# Try again with that dependency built...

	def spawn_build(self, iface_name):
		try:
			subprocess.check_call([sys.executable, sys.argv[0], 'build'])
		except subprocess.CalledProcessError as ex:
			raise SafeException(str(ex))

	def build(self):
		self.seen = {}
		tasks.wait_for_blocker(self.recursive_build(self.iface_uri))

	def heading(self, msg):
		self.note((' %s ' % msg).center(76, '='))

	def note(self, msg):
		print msg

	def note_error(self, msg):
		print msg

class GUIHandler(handler.Handler):
	def downloads_changed(self):
		self.compiler.downloads_changed()

	def confirm_import_feed(self, pending, valid_sigs):
		return handler.Handler.confirm_import_feed(self, pending, valid_sigs)

	@tasks.aasync
	def confirm_install(self, message):
		from zeroinstall.injector.download import DownloadAborted
		from zeroinstall.gtkui import gtkutils
		import gtk
		box = gtk.MessageDialog(self.compiler.dialog,
					gtk.DIALOG_DESTROY_WITH_PARENT,
					gtk.MESSAGE_QUESTION, gtk.BUTTONS_CANCEL,
					message)
		box.set_position(gtk.WIN_POS_CENTER)

		install = gtkutils.MixedButton('Install', gtk.STOCK_OK)
		install.set_flags(gtk.CAN_DEFAULT)
		box.add_action_widget(install, gtk.RESPONSE_OK)
		install.show_all()
		box.set_default_response(gtk.RESPONSE_OK)
		box.show()

		response = gtkutils.DialogResponse(box)
		yield response
		box.destroy()

		if response.response != gtk.RESPONSE_OK:
			raise DownloadAborted()

class GTKAutoCompiler(AutoCompiler):
	def __init__(self, config, iface_uri, options):
		config.handler.compiler = self

		AutoCompiler.__init__(self, config, iface_uri, options)
		self.child = None

		import pygtk; pygtk.require('2.0')
		import gtk

		w = gtk.Dialog('Autocompile %s' % iface_uri, None, 0,
						 (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
						  gtk.STOCK_OK, gtk.RESPONSE_OK))
		self.dialog = w

		w.set_default_size(int(gtk.gdk.screen_width() * 0.8),
				   int(gtk.gdk.screen_height() * 0.8))

		vpaned = gtk.VPaned()
		w.vbox.add(vpaned)
		w.set_response_sensitive(gtk.RESPONSE_OK, False)

		class AutoScroller:
			def __init__(self):
				tv = gtk.TextView()
				tv.set_property('left-margin', 8)
				tv.set_wrap_mode(gtk.WRAP_WORD_CHAR)
				tv.set_editable(False)
				swin = gtk.ScrolledWindow()
				swin.add(tv)
				swin.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
				buffer = tv.get_buffer()

				heading = buffer.create_tag('heading')
				heading.set_property('scale', 1.5)

				error = buffer.create_tag('error')
				error.set_property('background', 'white')
				error.set_property('foreground', 'red')

				self.tv = tv
				self.widget = swin
				self.buffer = buffer

			def insert_at_end_and_scroll(self, data, *tags):
				vscroll = self.widget.get_vadjustment()
				if not vscroll:
					# Widget has been destroyed
					print data,
					return
				near_end = vscroll.upper - vscroll.page_size * 1.5 < vscroll.value
				end = self.buffer.get_end_iter()
				self.buffer.insert_with_tags_by_name(end, data, *tags)
				if near_end:
					cursor = self.buffer.get_insert()
					self.buffer.move_mark(cursor, end)
					self.tv.scroll_to_mark(cursor, 0, False, 0, 0)

			def set_text(self, text):
				self.buffer.set_text(text)

		self.overall = AutoScroller()
		self.details = AutoScroller()

		vpaned.pack1(self.overall.widget, True, False)
		vpaned.pack2(self.details.widget, True, False)

		self.closed = tasks.Blocker('Window closed')

		w.show_all()
		w.connect('destroy', lambda wd: self.closed.trigger())

		def response(wd, resp):
			if self.child is not None:
				self.note_error('Sending TERM signal to build process group %d...' % self.child.pid)
				os.kill(-self.child.pid, signal.SIGTERM)
			else:
				self.closed.trigger()
		w.connect('response', response)

	def downloads_changed(self):
		if self.config.handler.monitored_downloads:
			msg = 'Downloads in progress:\n'
			for x in self.config.handler.monitored_downloads:
				msg += '- {url}\n'.format(url = x.url)
		else:
			msg = ''
		self.details.set_text(msg)

	def heading(self, msg):
		self.overall.insert_at_end_and_scroll(msg + '\n', 'heading')

	def note(self, msg):
		self.overall.insert_at_end_and_scroll(msg + '\n')

	def note_error(self, msg):
		self.overall.insert_at_end_and_scroll(msg + '\n', 'error')

	def build(self):
		self.seen = {}
		import gtk
		try:
			tasks.wait_for_blocker(self.recursive_build(self.iface_uri))
		except SafeException, ex:
			self.note_error(str(ex))
		else:
			self.heading('All builds completed successfully!')
			self.dialog.set_response_sensitive(gtk.RESPONSE_CANCEL, False)
			self.dialog.set_response_sensitive(gtk.RESPONSE_OK, True)

		tasks.wait_for_blocker(self.closed)

	@tasks.aasync
	def spawn_build(self, iface_name):
		assert self.child is None

		self.details.insert_at_end_and_scroll('Building %s\n' % iface_name, 'heading')

		# Group all the child processes so we can kill them easily
		def become_group_leader():
			os.setpgid(0, 0)
		devnull = os.open(os.devnull, os.O_RDONLY)
		try:
			self.child = subprocess.Popen([sys.executable, '-u', sys.argv[0], 'build'],
							stdin = devnull,
							stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
							preexec_fn = become_group_leader)
		finally:
			os.close(devnull)

		import codecs
		decoder = codecs.getincrementaldecoder('utf-8')(errors = 'replace')

		while True:
			yield tasks.InputBlocker(self.child.stdout, 'output from child')
			got = os.read(self.child.stdout.fileno(), 100)
			chars = decoder.decode(got, final = not got)
			self.details.insert_at_end_and_scroll(chars)
			if not got: break

		self.child.wait()
		code = self.child.returncode
		self.child = None
		if code:
			self.details.insert_at_end_and_scroll('Build process exited with error status %d\n' % code, 'error')
			raise SafeException('Build process exited with error status %d' % code)
		self.details.insert_at_end_and_scroll('Build completed successfully\n', 'heading')

	@tasks.aasync
	def confirm_import_feed(self, pending, valid_sigs):
		from zeroinstall.gtkui import trust_box
		box = trust_box.TrustBox(pending, valid_sigs, parent = self.dialog)
		box.show()
		yield box.closed

def do_autocompile(args):
	"""autocompile [--gui] URI"""

	parser = OptionParser(usage="usage: %prog autocompile [options]")

	parser.add_option('', "--gui", help="graphical interface", action='store_true')
	(options, args2) = parser.parse_args(args)
	if len(args2) != 1:
		raise __main__.UsageError()

	if options.gui:
		h = GUIHandler()
	elif os.isatty(1):
		h = handler.ConsoleHandler()
	else:
		h = handler.Handler()
	config = load_config(handler = h)
	config._iface_cache = AutocompileCache()

	iface_uri = model.canonical_iface_uri(args2[0])
	if options.gui:
		compiler = GTKAutoCompiler(config, iface_uri, options)
	else:
		compiler = AutoCompiler(config, iface_uri, options)

	compiler.build()

__main__.commands += [do_autocompile]
