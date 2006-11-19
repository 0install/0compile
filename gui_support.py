# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

import sys, os, popen2
import pygtk; pygtk.require('2.0')
import gtk, gobject

class CompileBox(gtk.Dialog):
	child = None

	def __init__(self, title):
		gtk.Dialog.__init__(self)
		self.set_has_separator(False)
		self.set_title(title)
		self.set_default_size(gtk.gdk.screen_width() / 2, gtk.gdk.screen_height() / 2)

		self.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_OK)

		self.buffer = gtk.TextBuffer()
		self.tv = gtk.TextView(self.buffer)
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
			if self.kill_child(): return
			self.destroy()
		self.connect('response', response)
	
	def kill_child(self):
		if self.child is None: return False

		import signal
		self.killed = True
		self.insert_at_end_and_scroll('\nSending SIGTERM to build process...\n')
		os.kill(-self.child, signal.SIGTERM)
		return True

	def run_command(self, command, success):
		assert self.child is None
		self.killed = False
		self.success = success
		if isinstance(command, basestring):
			self.buffer.insert_at_cursor("Running: " + command + "\n")
		else:
			self.buffer.insert_at_cursor("Running: " + ' '.join(command) + "\n")

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

		# We are the parent
		gobject.io_add_watch(r, gobject.IO_IN | gobject.IO_HUP, self.got_data)

	def insert_at_end_and_scroll(self, data):
		near_end = self.vscroll.upper - self.vscroll.page_size * 1.5 < self.vscroll.value
		end = self.buffer.get_end_iter()
		self.buffer.insert(end, data)
		if near_end:
			cursor = self.buffer.get_insert()
			self.buffer.move_mark(cursor, end)
			self.tv.scroll_to_mark(cursor, 0, False, 0, 0)
	
	def got_data(self, src, cond):
		data = os.read(src, 100)
		if data:
			self.insert_at_end_and_scroll(data)
			return True
		else:
			pid, status = os.waitpid(self.child, 0)
			assert pid == self.child
			self.child = None

			if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
				self.insert_at_end_and_scroll("Command complete.\n")
				self.success()
			elif self.killed:
				self.insert_at_end_and_scroll("Command terminated at user's request.\n")
			else:
				self.insert_at_end_and_scroll("Command failed.\n")
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
