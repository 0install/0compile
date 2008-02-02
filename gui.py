# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

# This is normally called by 0launch's GUI.

import sys, os, __main__
from zeroinstall.injector.iface_cache import iface_cache
from logging import info

from support import *

def do_gui(args):
	"gui [--no-prompt] [SOURCE-URI]"
	prompt = True
	if args and args[0] == '--no-prompt':
		del args[0]
		prompt = False

	import gui_support
	import gtk

	if len(args) == 0:
		env = BuildEnv()
		interface = env.interface
		build_dir = None
		prompt = False
	elif len(args) == 1:
		interface = args[0]
		default_dir = os.path.basename(interface)
		if default_dir.endswith('.xml'):
			default_dir = default_dir[:-4]
		assert '/' not in default_dir

		interface = model.canonical_iface_uri(args[0])

		build_dir = gui_support.choose_dir(_('Create build directory'), default_dir)
		if not build_dir: return
	else:
		raise __main__.UsageError()

	try:
		import setup
		setup.setup(interface, build_dir, prompt)
		if build_dir:
			os.chdir(build_dir)

		box = gui_support.CompileBox(interface)
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
