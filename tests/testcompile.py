#!/usr/bin/env python
import sys, tempfile, os, shutil, tempfile, subprocess
from StringIO import StringIO
import unittest
from zeroinstall.injector import model, qdom, config
from zeroinstall.support import ro_rmtree, basedir
from zeroinstall.zerostore import Stores

stores = Stores()

mydir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(mydir))
import support

hello_uri = 'http://0install.net/tests/GNU-Hello.xml'

mydir = os.path.realpath(os.path.dirname(__file__))

hello_selections = os.path.join(mydir, 'selections.xml')
local_bad_version = os.path.join(mydir, 'bad-version.xml')
local_hello_path = os.path.join(mydir, 'hello2', 'hello2.xml')
local_cprog_command_path = os.path.join(mydir, 'cprog', 'cprog-command.xml')
local_cprog_path = os.path.join(mydir, 'cprog', 'cprog.xml')
top_build_deps = os.path.join(mydir, 'top-build-deps.xml')

compile_bin = os.path.join(mydir, '0compile-coverage')
assert os.path.exists(compile_bin)

if 'DISPLAY' in os.environ:
	del os.environ['DISPLAY']

launch_command = [os.environ['0COMPILE_0LAUNCH']]

# Ensure it's cached now, to avoid extra output during the tests
if subprocess.call(launch_command + ['--source', '-c', '--download-only', hello_uri]):
	raise Exception("Failed to download hello world test program")

def compile(*args, **kwargs):
	run(*([sys.executable, compile_bin] + list(args)), **kwargs)

def run(*args, **kwargs):
	if not isinstance(args[0], basestring):
		args = args[0] + list(args[1:])
	child = subprocess.Popen(args, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
	got, unused = child.communicate()
	code = child.wait()
	if code != kwargs.get('expect_status', 0):
		raise Exception("Exit status %d:\n%s" % (code, got))

	expected = kwargs.get('expect', '')
	if expected:
		if expected.lower() not in got.lower():
			raise Exception("Expected '%s', got '%s'" % (expected, got))
	elif got:
		raise Exception("Expected nothing, got '%s'" % got)

# Detect accidental network access
os.environ['http_proxy'] = 'localhost:1111'

for x in ['GNUPGHOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME']:
	if x in os.environ:
		del os.environ[x]
user_cache_dir = os.environ['XDG_CACHE_DIRS'] = basedir.xdg_cache_home

class TestCompile(unittest.TestCase):
	def setUp(self):
		os.chdir('/')
		self.tmpdir = tempfile.mkdtemp(prefix = '0compile-test-')
		self.hello_dir = os.path.join(self.tmpdir, 'hello')

		os.environ['HOME'] = self.tmpdir
		reload(basedir)

		config_dir = basedir.save_config_path('0install.net', 'injector')
		stream = open(os.path.join(config_dir, 'implementation-dirs'), 'w')
		for x in stores.stores:
			stream.write(x.dir + '\n')
		stream.close()

		stream = open(os.path.join(config_dir, 'global'), 'w')
		stream.write('[global]\n'
				'freshness = -1\n'
				'help_with_testing = True\n'
				'network_use = off-line\n')
		stream.close()
	
	def tearDown(self):
		os.chdir(os.path.join(self.tmpdir, os.path.pardir))
		ro_rmtree(self.tmpdir)

	def testBadCommand(self):
		compile('foo', expect = 'usage: 0compile', expect_status = 1)
		compile('setup', hello_uri, self.tmpdir, expect = 'already exists', expect_status = 1)
		os.chdir(self.tmpdir)
		compile('setup', expect = 'Run 0compile from a directory containing', expect_status = 1)
		compile('build', expect = 'Run 0compile from a directory containing', expect_status = 1)
		compile('publish', expect = 'Run 0compile from a directory containing', expect_status = 1)

	def testCompileNoDir(self):
		os.chdir(self.tmpdir)
		compile('setup', hello_uri, expect = 'Created directory')
		os.chdir('GNU-Hello')

	def testCompile(self):
		compile('setup', hello_uri, self.hello_dir, expect = 'Created directory')
		os.chdir(self.hello_dir)

		compile('build', expect = 'Executing: "%s"' % os.path.join('$SRCDIR','configure'))

		target_dir = 'gnu-hello-%s' % support.get_arch_name().lower()
		archive_stem = 'gnu-hello-%s-1.3' % support.get_arch_name().lower()
		assert os.path.isdir(target_dir), '%s not a directory' % target_dir

		run(os.path.join(target_dir,'bin','hello'), expect = 'Hello, world!')
		run(launch_command, os.path.join(target_dir,'0install', 'feed.xml'), expect = 'Hello, world!')
		compile('publish', 'http://localhost/downloads', expect = "Now upload '%s.tar.bz2'" % archive_stem)
	
	def testAutocompile(self):
		compile('autocompile', hello_uri, expect = "site-packages/http/0install.net/tests__GNU-Hello.xml")
		run(launch_command, hello_uri, expect = 'Hello, world!')

	def testRecursive(self):
		top = os.path.join(mydir, 'top.xml')
		compile('autocompile', top, expect = "No dependencies need compiling... compile cprog itself...")

		# Dependency was registered against its local path, since that was how we depended on it:
		run(launch_command, os.path.join(mydir, 'cprog/cprog-command.xml'), expect = 'Hello from C')

		# But the top-level feed was registered against its <feed-for>:
		c = config.load_config()
		i = c.iface_cache.get_interface('http://example.com/top.xml')
		self.assertEquals(1, len(i.extra_feeds))

	def testLocal(self):
		compile('setup', local_hello_path, self.hello_dir, expect = 'Created directory')
		os.chdir(self.hello_dir)
		compile('build', expect = 'Executing: ls -l')
		target_dir = 'hello2-any-any'
		assert os.path.isdir(target_dir), '%s not a directory' % target_dir

		run(launch_command, os.path.join(target_dir, '0install', 'feed.xml'), expect = 'ROX-Lib')
	
	def testBadVersion(self):
		compile('setup', local_bad_version, self.hello_dir, expect = 'Created directory')
		os.chdir(self.hello_dir)
		compile('build', expect = 'hello2-0.1 requires 0compile >= 300000', expect_status = 1)

	def testCommand(self):
		comp_dir = os.path.join(self.tmpdir, 'cprog-command')
		compile('setup', local_cprog_command_path, comp_dir, expect = 'Created directory')
		os.chdir(comp_dir)
		compile('build', expect = 'Hello from C!')
		target_dir = 'cprog-command-%s' % support.get_arch_name().lower()
		binary_feed = os.path.join(target_dir, '0install', 'feed.xml')
		run(launch_command, binary_feed, expect = 'Hello from C!')
		s = open(binary_feed, 'r')
		feed = model.ZeroInstallFeed(qdom.parse(s), binary_feed)
		s.close()
		impl, = feed.implementations.values()
		assert impl.arch, "Missing arch on %s" % impl

	def testCopySrc(self):
		comp_dir = os.path.join(self.tmpdir, 'cprog')
		compile('setup', local_cprog_path, comp_dir, expect = 'Created directory')
		os.chdir(comp_dir)
		compile('diff', expect = "No local src directory to diff against", expect_status = 1)
		compile('diff', 'foo', expect = 'usage', expect_status = 1)
		compile('copy-src', 'foo', expect = 'usage', expect_status = 1)
		compile('copy-src', expect = 'Copied as')
		compile('copy-src', expect = "Directory '", expect_status = 1)

		# 'src' exists, but no changes
		compile('diff')
		compile('--verbose', 'build', expect = 'Hello from C')
		target_dir = 'cprog-%s' % support.get_arch_name().lower()
		patch_file = os.path.join(target_dir, '0install', 'from-0.1.patch')
		assert not os.path.exists(patch_file)

		# 'src' contains a change
		prog = file(os.path.join('src','main.c')).read()
		prog = prog.replace('Hello', 'Goodbye')
		stream = file(os.path.join('src','main.c'), 'w')
		stream.write(prog)
		stream.close()
		compile('diff', expect = 'diff')
		shutil.rmtree('build')
		compile('build', expect = 'Goodbye from C')
		assert os.path.exists(patch_file)

		# Test dup-src's unlinking while we're here
		compile('build', expect = 'Goodbye from C')

		# 'src' contains an error
		stream = file(os.path.join('src','main.c'), 'w')
		stream.write('this is not valid C!')
		stream.close()
		shutil.rmtree('build')
		compile('build', expect = 'Build failed', expect_status = 1)
		assert os.path.exists(os.path.join('build', 'build-failure.log'))

		# 'src' does not exist
		shutil.rmtree('src')
		shutil.rmtree('build')
		compile('build', expect = 'Hello from C')
		assert not os.path.exists(patch_file)

		# Check we fixed the .pc files...
		pc_data = open(os.path.join(target_dir, 'pkgconfig', 'cprog.pc')).read()
		assert pc_data == "prefix=" + os.path.join("${pcfiledir}",os.path.pardir) + "\n", `pc_data`

		# Check we removed the bad .la files...
		assert not os.path.exists(os.path.join(target_dir, 'lib', 'bad.la'))	# libtool - bad
		assert os.path.exists(os.path.join(target_dir, 'lib', 'good.la'))	# Ends in .la, but not a libtool archive
		assert os.path.exists(os.path.join(target_dir, 'lib', 'nice.ok'))	# Doesn't end in .la

	def testInlcudeDeps(self):
		compile('setup', hello_uri, self.hello_dir, expect = 'Created directory')
		os.chdir(self.hello_dir)
		os.unlink('0compile.properties')
		compile('setup', hello_uri, '.')
		compile('include-deps', expect = 'dependencies to')
		compile('include-deps', expect = 'Copied 0 depend')

	def testSetup(self):
		compile('setup', hello_selections, self.hello_dir,
			expect = 'Created directory')
		compile('setup', hello_selections, self.hello_dir,
			expect = "Directory '", expect_status = 1)
		compile('setup', hello_selections, '.', 'foo',
			expect = "usage", expect_status = 1)
		os.chdir(self.hello_dir)
		compile('setup', expect = "Selections are fixed", expect_status = 1)

	def testReportBug(self):
		broken_src = os.path.join(self.hello_dir, "broken.xml")
		os.mkdir(self.hello_dir)
		shutil.copy(local_hello_path, broken_src)
		os.chdir(self.hello_dir)
		compile('setup', broken_src, '.')
		compile('build', expect = 'Build failed with exit code', expect_status = 1)
		compile('report-bug', expect = "http://0install.net/api/report-bug")

		env = support.BuildEnv()
		os.unlink(os.path.join(env.metadir, "build-environment.xml"))
		compile('report-bug', expect = "file+not+found")
	
	def testBuildDeps(self):
		compile('autocompile', top_build_deps, expect = "build-deps.xml 0.1 requires 3 <= version < 3", expect_status = 1)

suite = unittest.makeSuite(TestCompile)
if __name__ == '__main__':
	unittest.main()
