# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, __main__, popen2
import pygtk; pygtk.require('2.0')
import gtk, gobject
from zeroinstall.injector import reader, writer

from support import *

RESPONSE_SETUP = 1
RESPONSE_BUILD = 2
RESPONSE_PUBLISH = 3
RESPONSE_REGISTER = 4

action_responses = [RESPONSE_SETUP, RESPONSE_BUILD, RESPONSE_PUBLISH, RESPONSE_REGISTER]

main_path = os.path.abspath(__main__.__file__)
	
class CompileBox(gtk.Dialog):
	child = None

	def __init__(self, interface):
		gtk.Dialog.__init__(self, _("Compile '%s'") % interface.split('/')[-1])	# No rsplit on Python 2.3
		self.set_has_separator(False)
		self.set_default_size(gtk.gdk.screen_width() / 2, gtk.gdk.screen_height() / 2)

		def add_action(stock, name, resp):
			if not hasattr(gtk, stock):
				stock = 'STOCK_YES'
			button = ButtonMixed(getattr(gtk, stock), name)
			button.set_flags(gtk.CAN_DEFAULT)
			self.add_action_widget(button, resp)
			return button

		add_action('STOCK_PROPERTIES', '_Setup', RESPONSE_SETUP)
		add_action('STOCK_CONVERT', '_Build', RESPONSE_BUILD)
		add_action('STOCK_ADD', '_Register', RESPONSE_REGISTER)
		add_action('STOCK_NETWORK', '_Publish', RESPONSE_PUBLISH)

		self.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CANCEL)

		self.set_default_response(RESPONSE_BUILD)

		self.buffer = gtk.TextBuffer()
		self.tv = gtk.TextView(self.buffer)
		self.tv.set_left_margin(4)
		self.tv.set_right_margin(4)
		self.tv.set_wrap_mode(gtk.WRAP_WORD)
		swin = gtk.ScrolledWindow()
		swin.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_ALWAYS)
		swin.add(self.tv)
		swin.set_shadow_type(gtk.SHADOW_IN)
		self.vscroll = swin.get_vadjustment()
		self.tv.set_editable(False)
		self.tv.set_cursor_visible(False)
		self.vbox.pack_start(swin, True, True, 0)

		self.vbox.show_all()
	
		self.connect('delete-event', lambda box, dev: True)

		def response(box, resp):
			if resp == RESPONSE_SETUP:
				import setup
				def done_setup():
					buildenv = BuildEnv()
					to_delete = [x for x in ['build', buildenv.distdir] if os.path.isdir(x)]
					if not to_delete:
						pass
					elif confirm(self, ("After changing source versions, it's a "
						"good idea to delete the existing build files (%s). Delete existing directories?") %
						' and '.join(['"%s"' % d for d in to_delete]), gtk.STOCK_CLEAR):
						def done_clean():
							self.add_msg('Now use Build to compile the chosen source code.')
						self.run_command([find_in_path('rm'), '-rf'] + to_delete, done_clean)
						return
					else:
						self.add_msg('Not cleaning up existing build files.')
					self.add_msg('Now use Build to compile the chosen source code.')
				self.run_command((sys.executable, main_path, 'setup'), done_setup)
			elif resp == RESPONSE_BUILD:
				def done_build():
					self.add_msg('\nBuild successful. Now register or publish the build.')
				def build_failed():
					self.add_msg('\nIf the messages displayed above indicate a missing dependency (e.g. no C compiler '
						     "or a library that isn't available through Zero Install) then install it using your "
						     'normal package manager and click on Build again. Note that for libraries you often '
						     'need the -dev version of the package. '
						     '\nOtherwise, please notify the developers of this problem (this will transmit '
						     'the contents of the build/build-failure.log file):')
					end = self.buffer.get_end_iter()
					anchor = self.buffer.create_child_anchor(end)
					align = gtk.Alignment(0.0, 0.0, 1.0, 1.0)
					button = ButtonMixed(gtk.STOCK_YES, 'Notify developers')
					align.add(button)
					align.set_padding(8, 8, 8, 8)
					align.show_all()
					self.tv.add_child_at_anchor(align, anchor)
					self.add_msg('\n')
					def report_bug(button):
						def done_notify():
							self.add_msg("\nReport sent. Thank you! (note: you won't get a reply, as "
								"no contact details were sent; write to the project's mailing "
								"list if you want to discuss the problem)")
						self.run_command((sys.executable, main_path, 'report-bug'), done_notify)
					button.connect('clicked', report_bug)
				box.run_command((sys.executable, main_path, 'build'), done_build, build_failed)
			elif resp == RESPONSE_REGISTER:
				buildenv = BuildEnv()

				iface = iface_cache.get_interface(interface)
				reader.update_from_cache(iface)
				feed = buildenv.local_iface_file
				for f in iface.feeds or []:
					if f.uri == feed:
						self.add_msg("Feed '%s' is already registered for interface '%s'!\n" % (feed, iface.uri))
						return
				box.buffer.insert_at_cursor("Registering feed '%s'\n" % feed)
				iface.feeds.append(model.Feed(feed, arch = None, user_override = True))
				writer.save_interface(iface)
				box.buffer.insert_at_cursor("You can now close this window.\n")
			elif resp == RESPONSE_PUBLISH:
				buildenv = BuildEnv()
				box = PublishBox(self, buildenv)
				resp = box.run()
				box.destroy()
				if resp == gtk.RESPONSE_OK:
					def done_publish():
						self.add_msg("\nYou can use '0publish --local' to add this "
							"into the main feed. If you don't have a main feed then this "
							"will create one. See"
							"http://0install.net/injector-packagers.html for more information.")
					self.run_command((sys.executable, main_path,
						'publish', box.archive_dir.get_text()), done_publish)
			elif resp == gtk.RESPONSE_CANCEL or resp == gtk.RESPONSE_DELETE_EVENT:
				if self.kill_child(): return
				self.destroy()
			else:
				self.add_msg('Unknown response: %s' % resp)
				
		self.connect('response', response)

		self.system_tag = self.buffer.create_tag('system', foreground = 'blue', background = 'white')
		self.add_msg(instructions)
		self.set_responses_sensitive()
	
	def kill_child(self):
		if self.child is None: return False

		import signal
		self.killed = True
		self.add_msg('\nSending SIGTERM to process...')
		os.kill(-self.child, signal.SIGTERM)
		return True
	
	def add_msg(self, msg):
		self.insert_at_end_and_scroll(msg + '\n', self.system_tag)

	"""Run command in a sub-process.
	Calls success() if the command exits with status zero.
	Calls failure() if it fails for other reasons.
	(neither is called if the user aborts the command)"""
	def run_command(self, command, success, failure = None):
		assert self.child is None
		self.killed = False
		self.success = success
		self.failure = failure
		if isinstance(command, basestring):
			self.add_msg("Running: " + command + "\n")
		else:
			self.add_msg("Running: " + ' '.join(command) + "\n")

		r, w = os.pipe()
		try:
			try:
				self.child = os.fork()
				if not self.child:
					# We are the child
					try:
						try:
							os.close(r)
							os.dup2(w, 1)
							os.dup2(w, 2)
							os.close(w)
							os.setpgrp()	# Become group leader
							os.execvp(command[0], command)
						except:
							import traceback
							traceback.print_exc()
					finally:
						os._exit(1)
			finally:
				os.close(w)
		except:
			os.close(r)
			raise

		for resp in action_responses:
			self.set_response_sensitive(resp, False)

		# We are the parent
		gobject.io_add_watch(r, gobject.IO_IN | gobject.IO_HUP, self.got_data)
	
	def set_responses_sensitive(self):
		self.set_response_sensitive(RESPONSE_SETUP, True)
		self.set_response_sensitive(RESPONSE_BUILD, True)

		buildenv = BuildEnv()
		have_binary = os.path.exists(buildenv.local_iface_file)
		self.set_response_sensitive(RESPONSE_REGISTER, have_binary)
		self.set_response_sensitive(RESPONSE_PUBLISH, have_binary)

	def insert_at_end_and_scroll(self, data, *tags):
		near_end = self.vscroll.upper - self.vscroll.page_size * 1.5 < self.vscroll.value
		end = self.buffer.get_end_iter()
		self.buffer.insert_with_tags(end, data, *tags)
		if near_end:
			cursor = self.buffer.get_insert()
			self.buffer.move_mark(cursor, end)
			self.tv.scroll_to_mark(cursor, 0, False, 0, 0)
	
	def got_data(self, src, cond):
		data = os.read(src, 100)
		if data:
			# TODO: only insert complete UTF-8 sequences, not half sequences
			self.insert_at_end_and_scroll(data)
			return True
		else:
			pid, status = os.waitpid(self.child, 0)
			assert pid == self.child
			self.child = None

			self.set_responses_sensitive()

			if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
				self.success()
			elif self.killed:
				self.add_msg("\nCommand terminated at user's request.")
			else:
				self.add_msg("\nCommand failed.")
				if self.failure:
					self.failure()
			return False


def choose_dir(title, default):
	sel = gtk.FileSelection(title)
	sel.set_has_separator(False)
	sel.set_filename(default)
	while True:
		resp = sel.run()
		if resp == gtk.RESPONSE_OK:
			build_dir = sel.get_filename()
			if not os.path.exists(build_dir):
				sel.destroy()
				return build_dir
			alert(sel, _("'%s' already exists") % build_dir)
		else:
			sel.destroy()
			return None

def alert(parent, msg):
	d = gtk.MessageDialog(parent,
		     gtk.DIALOG_MODAL,
		     gtk.MESSAGE_ERROR,
		     gtk.BUTTONS_OK,
		     msg)
	d.run()
	d.destroy()

class ButtonMixed(gtk.Button):
	"""A button with a standard stock icon, but any label. This is useful
	when you want to express a concept similar to one of the stock ones."""
	def __init__(self, stock, message):
		"""Specify the icon and text for the new button. The text
		may specify the mnemonic for the widget by putting a _ before
		the letter, eg:
		button = ButtonMixed(gtk.STOCK_DELETE, '_Delete message')."""
		gtk.Button.__init__(self)
	
		label = gtk.Label('')
		label.set_text_with_mnemonic(message)
		label.set_mnemonic_widget(self)

		image = gtk.image_new_from_stock(stock, gtk.ICON_SIZE_BUTTON)
		box = gtk.HBox(False, 2)
		align = gtk.Alignment(0.5, 0.5, 0.0, 0.0)

		box.pack_start(image, False, False, 0)
		box.pack_end(label, False, False, 0)

		self.add(align)
		align.add(box)
		align.show_all()

def confirm(parent, message, stock_icon, action = None):
	"""Display a <Cancel>/<Action> dialog. Result is true if the user
	chooses the action, false otherwise. If action is given then that
	is used as the text instead of the default for the stock item. Eg:
	if rox.confirm('Really delete everything?', gtk.STOCK_DELETE): delete()
	"""
	box = gtk.MessageDialog(parent, 0, gtk.MESSAGE_QUESTION,
				gtk.BUTTONS_CANCEL, message)
	if action:
		button = ButtonMixed(stock_icon, action)
	else:
		button = gtk.Button(stock = stock_icon)
	button.set_flags(gtk.CAN_DEFAULT)
	button.show()
	box.add_action_widget(button, gtk.RESPONSE_OK)
	box.set_position(gtk.WIN_POS_CENTER)
	box.set_title(_('Confirm:'))
	box.set_default_response(gtk.RESPONSE_OK)
	resp = box.run()
	box.destroy()
	return resp == int(gtk.RESPONSE_OK)

class PublishBox(gtk.MessageDialog):
	def __init__(self, parent, buildenv):
		gtk.MessageDialog.__init__(self, parent,
			gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
			gtk.MESSAGE_QUESTION, gtk.BUTTONS_OK_CANCEL,
			'Enter the directory on your HTTP or FTP server to which '
			'the archive file will be uploaded:')
		vbox = gtk.VBox(True, 4)
		self.vbox.pack_start(vbox, False, True, 0)
		vbox.set_border_width(8)

		self.archive_dir = gtk.Entry()
		self.archive_dir.set_activates_default(True)
		self.set_default_response(gtk.RESPONSE_OK)

		if buildenv.download_base_url:
			self.archive_dir.set_text(buildenv.download_base_url)
		else:
			self.archive_dir.set_text('http://myserver.com/archives')

		vbox.pack_start(self.archive_dir, False, True, 0)
		vbox.show_all()

instructions = """Instructions

Compiling a program takes the program's human readable source code, and generates a binary which a computer can run.

To choose a different version of the source code, or the versions of any other programs needed to compile, use Setup.

To compile the chosen source code into a binary, use Build.

To add the new binary to the list of available versions for the program, use Register.

To publish the binary on the web, so that other people can run it, use Publish.

For further information, including details of how to make changes to the source code before compiling, visit: http://0install.net/0compile.html
"""
