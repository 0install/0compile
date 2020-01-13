# Copyright (C) 2006, Thomas Leonard
# See http://0install.net/0compile.html

# This is normally called by 0launch's GUI.

import sys, __main__

from zeroinstall import SafeException

from support import BuildEnv, _

def do_gui(args):
	"gui [--no-prompt] [SOURCE-URI]"
	if args and args[0] == '--no-prompt':
		del args[0]
		# This option no longer has any effect, since it is the default.
		# However, old versions of 0launch's GUI pass it (< 0.52)

	import gui_support
	import gtk

	try:
		if len(args) == 0:
			pass
		elif len(args) == 1:
			import setup
			def get_dir_callback(default_dir):
				compile_dir = gui_support.choose_dir(_('Create build directory'), default_dir)
				if compile_dir:
					return compile_dir
				raise SafeException("Cancelled at user's request")
			setup.do_setup(args, get_dir_callback)
		else:
			raise SafeException("usage: 0compile gui URI")

		buildenv = BuildEnv()
		box = gui_support.CompileBox(buildenv.interface)
		box.connect('destroy', lambda b: gtk.main_quit())
		box.show()

		gtk.main()
	except KeyboardInterrupt:
		pass
	except SafeException as ex:
		gui_support.alert(None, '%s' % ex)
		sys.exit(1)
	except Exception as ex:
		import traceback
		traceback.print_exc()
		gui_support.alert(None, '%s: %s' % (ex.__class__, ex))
		sys.exit(1)

__main__.commands.append(do_gui)
