# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

# This is normally called by 0launch's GUI.

import sys, os, __main__
from zeroinstall.injector.iface_cache import iface_cache
from zeroinstall.injector import writer
from logging import info

from support import *

def do_gui(args):
	"gui [--no-prompt] SOURCE-URI"
	main_path = os.path.abspath(__main__.__file__)
	print main_path
	
	prompt = True
	if args and args[0] == '--no-prompt':
		del args[0]
		prompt = False

	if len(args) != 1:
		raise __main__.UsageError()

	interface = args[0]
	default_dir = os.path.basename(interface)
	if default_dir.endswith('.xml'):
		default_dir = default_dir[:-4]
	assert '/' not in default_dir

	interface = model.canonical_iface_uri(args[0])

	import gui_support
	import gtk
	build_dir = gui_support.choose_dir(_('Create build directory'), default_dir)

	try:
		import setup
		setup.setup(interface, build_dir, prompt, create_dir = True)
		os.chdir(build_dir)

		box = gui_support.CompileBox(_("Compile '%s'") % default_dir)
		box.connect('response', lambda b, r: gtk.main_quit())
		box.show()

		def register_feed():
			buildenv = BuildEnv()

			iface = iface_cache.get_interface(interface)
			feed = buildenv.local_iface_file
			box.buffer.insert_at_cursor("\nRegistering feed '%s'\n" % feed)
			iface.feeds.append(model.Feed(feed, arch = None, user_override = True))
			writer.save_interface(iface)
			box.buffer.insert_at_cursor("\nYou can now close this window.")

		box.run((sys.executable, main_path, 'build'), register_feed)

		gtk.main()
	except Exception, ex:
		import traceback
		traceback.print_exc()
		gui_support.alert(None, '%s: %s' % (ex.__class__, ex))

__main__.commands.append(do_gui)
