# Copyright (C) 2009, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__, tempfile, subprocess, signal
from xml.dom import minidom
from optparse import OptionParser

from zeroinstall import SafeException
from zeroinstall.injector import arch, handler, policy, model, iface_cache, selections, namespaces, writer, reader
from zeroinstall.zerostore import manifest, NotStored
from zeroinstall.support import tasks, basedir, ro_rmtree

from support import BuildEnv, uname

# This is a bit hacky...
#
# We invent a new CPU type which is compatible with the host but worse than
# every existing type, and we use * for the OS type so that we don't beat 'Any'
# binaries either. This means that we always prefer an existing binary of the
# desired version to compiling a new one, but we'll compile a new version from source
# rather than use an older binary.
arch.machine_groups['newbuild'] = arch.machine_groups.get(uname[-1], 0)
arch.machine_ranks['newbuild'] = max(arch.machine_ranks.values()) + 1
host_arch = '*-newbuild'

class DummyDownloadSource(model.RetrievalMethod):
	"""0launch >= 0.46 won't select implementations without a download source."""
	pass

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
					new = model.ZeroInstallImplementation(feed, new_id, None)
					new.download_sources.append(DummyDownloadSource())
					feed.implementations[new_id] = new
					new.digests.append(new_id)
					new.set_arch(host_arch)
					new.version = x.version

		return feed

class AutoCompiler:
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
			for x in impl.requires:
				self.pretty_print_plan(solver, x.interface, indent)

	def print_details(self, solver):
		"""Dump debugging details."""
		self.note("\nFailed. Details of all components and versions considered:")
		for iface in solver.details:
			self.note('\n%s\n' % iface.get_name())
			for impl, note in solver.details[iface]:
				self.note('%s (%s) : %s' % (impl.get_version(), impl.arch or '*-*', note or 'OK'))
		self.note("\nEnd details\n")

	@tasks.async
	def compile_and_register(self, policy):
		def valid_autocompile_feed(binary_feed):
			cache = policy.config.iface_cache
			local_feed_impls = cache.get_feed(local_feed).implementations
			if len(local_feed_impls) != 1:
				self.note("Invalid autocompile feed '%s'; expected exactly one implementation!" % binary_feed)
				return False
			impl, = local_feed_impls.values()
			try:
				cache.stores.lookup_any(impl.digests)
				return True
			except NotStored, ex:
				self.note("Build metadata file '%s' exists but implementation is missing: %s" % (local_feed, ex))
				return False

		local_feed_dir = basedir.save_config_path('0install.net', '0compile', 'builds', model._pretty_escape(policy.root))
		s = policy.solver.selections

		buildenv = BuildEnv(need_config = False)
		buildenv.config.set('compile', 'interface', policy.root)
		buildenv.config.set('compile', 'selections', 'selections.xml')
		
		# Download any required packages now, so we can use the GUI to request confirmation, etc
		download_missing = s.download_missing(self.config, include_packages = True)
		if download_missing:
			yield download_missing
			tasks.check(download_missing)

		version = s.selections[policy.root].version
		local_feed = os.path.join(local_feed_dir, '%s-%s-%s.xml' % (buildenv.iface_name, version, uname[-1]))
		if os.path.exists(local_feed):
			if not valid_autocompile_feed(local_feed):
				os.unlink(local_feed)
			else:
				raise SafeException("Build metadata file '%s' already exists!" % local_feed)

		tmpdir = tempfile.mkdtemp(prefix = '0compile-')
		try:
			os.chdir(tmpdir)

			# Write configuration for build...

			buildenv.save()

			sel_file = open('selections.xml', 'w')
			try:
				doc = s.toDOM()
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

			alg = manifest.get_algorithm('sha1new')
			digest = alg.new_digest()
			lines = []
			for line in alg.generate_manifest(buildenv.distdir):
				line += '\n'
				digest.update(line)
				lines.append(line)
			actual_digest = alg.getID(digest)

			local_feed_file = file(local_feed, 'w')
			try:
				dom = minidom.parse(buildenv.local_iface_file)
				impl, = dom.getElementsByTagNameNS(namespaces.XMLNS_IFACE, 'implementation')
				impl.setAttribute('id', actual_digest)
				dom.writexml(local_feed_file)
				local_feed_file.write('\n')
			finally:
				local_feed_file.close()

			feed_for_elem, = dom.getElementsByTagNameNS(namespaces.XMLNS_IFACE, 'feed-for')

			self.note("Implementation metadata written to %s" % local_feed)

			# No point adding it to the system store when only the user has the feed...
			store = policy.config.stores.stores[0]
			self.note("Storing build in user cache %s..." % store.dir)
			policy.config.stores.add_dir_to_cache(actual_digest, buildenv.distdir)

			iface = policy.config.iface_cache.get_interface(feed_for_elem.getAttribute('interface'))
			self.note("Registering as feed for %s" % iface.uri)
			feed = iface.get_feed(local_feed)
			if feed:
				self.note("WARNING: feed %s already registered!" % local_feed)
			else:
				iface.extra_feeds.append(model.Feed(local_feed, impl.getAttribute('arch'), user_override = True))
			writer.save_interface(iface)

			# We might have cached an old version
			new_feed = policy.config.iface_cache.get_interface(local_feed)
			reader.update_from_cache(new_feed)
		except:
			self.note("\nBuild failed: leaving build directory %s for inspection...\n" % tmpdir)
			raise
		else:
			ro_rmtree(tmpdir)

	@tasks.async
	def recursive_build(self, iface_uri, version = None):
		p = policy.Policy(iface_uri, config = self.config, src = True)
		iface = p.config.iface_cache.get_interface(iface_uri)
		p.solver.record_details = True
		if version:
			p.solver.extra_restrictions[iface] = [model.VersionRestriction(model.parse_version(version))]

		# For testing...
		#p.target_arch = arch.Architecture(os_ranks = {'FreeBSD': 0, None: 1}, machine_ranks = {'i386': 0, None: 1, 'newbuild': 2})

		while True:
			self.heading(iface_uri)
			self.note("\nSelecting versions for %s..." % iface.get_name())
			solved = p.solve_with_downloads()
			if solved:
				yield solved
				tasks.check(solved)

			if not p.solver.ready:
				self.print_details(p.solver)
				raise SafeException("Can't find all required implementations (source or binary):\n" +
					'\n'.join(["- %s -> %s" % (iface, p.solver.selections[iface])
						   for iface in p.solver.selections]))
			self.note("Selection done.")

			self.note("\nPlan:\n")
			self.pretty_print_plan(p.solver, p.root)
			self.note('')

			for dep_iface, dep_impl in p.solver.selections.iteritems():
				if dep_impl.id.startswith('0compile='):
					build = self.recursive_build(dep_iface.uri, dep_impl.get_version())
					yield build
					tasks.check(build)
					break	# Try again with that dependency built...
			else:
				self.note("No dependencies need compiling... compile %s itself..." % iface.get_name())
				build = self.compile_and_register(p)
				yield build
				tasks.check(build)
				return

	def spawn_build(self, iface_name):
		subprocess.check_call([sys.executable, sys.argv[0], 'build'])

	def build(self):
		tasks.wait_for_blocker(self.recursive_build(self.iface_uri))

	def heading(self, msg):
		self.note((' %s ' % msg).center(76, '='))

	def note(self, msg):
		print msg

	def note_error(self, msg):
		self.overall.insert_at_cursor(msg + '\n')

class GUIHandler(handler.Handler):
	def downloads_changed(self):
		self.compiler.downloads_changed()

	def confirm_import_feed(self, pending, valid_sigs):
		return handler.Handler.confirm_import_feed(self, pending, valid_sigs)

	@tasks.async
	def confirm_install(self, message):
		from zeroinstall.injector.download import DownloadAborted
		from zeroinstall.gtkui import gtkutils
		import gtk
		box = gtk.MessageDialog(self.compiler.dialog,
					gtk.DIALOG_DESTROY_WITH_PARENT,
					gtk.MESSAGE_QUESTION, gtk.BUTTONS_CANCEL,
					message)
		box.set_position(gtk.WIN_POS_CENTER)

		install = gtkutils.MixedButton(_('Install'), gtk.STOCK_OK)
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

	@tasks.async
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

	@tasks.async
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
	config = policy.load_config(handler = h)
	config._iface_cache = AutocompileCache()

	iface_uri = model.canonical_iface_uri(args2[0])
	if options.gui:
		compiler = GTKAutoCompiler(config, iface_uri, options)
	else:
		compiler = AutoCompiler(config, iface_uri, options)

	compiler.build()

__main__.commands += [do_autocompile]
