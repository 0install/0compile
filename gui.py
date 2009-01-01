# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

# This is normally called by 0launch's GUI.

import sys, os, __main__
from zeroinstall.injector.iface_cache import iface_cache
from logging import info

from support import *

def do_gui(args):
	"gui [--no-prompt] [SOURCE-URI]"
	if args and args[0] == '--no-prompt':
		del args[0]
		# This option no longer has any effect, since it is the default.
		# However, 0launch's GUI passes it.

	import gui_support
	import gtk

	try:
		if len(args) == 0:
			buildenv = BuildEnv()
		elif len(args) == 1:
			buildenv = BuildEnv(need_config = False)
			import setup
			def get_dir_callback(default_dir):
				compile_dir = gui_support.choose_dir(_('Create build directory'), default_dir)
				if compile_dir:
					return compile_dir
				raise SafeException("Cancelled at user's request")
			setup.do_setup(args, get_dir_callback)
		else:
			raise __main__.UsageError()

		box = gui_support.CompileBox(buildenv.interface)
		box.connect('destroy', lambda b: gtk.main_quit())
		box.show()

		gtk.main()
	except KeyboardInterrupt:
		pass
	except SafeException, ex:
		gui_support.alert(None, '%s' % ex)
		sys.exit(1)
	except Exception, ex:
		import traceback
		traceback.print_exc()
		gui_support.alert(None, '%s: %s' % (ex.__class__, ex))
		sys.exit(1)

__main__.commands.append(do_gui)
