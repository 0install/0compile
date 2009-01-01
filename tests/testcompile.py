#!/usr/bin/env python2.4
import sys, tempfile, os, shutil, tempfile, subprocess
from StringIO import StringIO
import unittest
from zeroinstall.support import ro_rmtree

sys.path.insert(0, '..')
import support

hello_uri = 'http://0install.net/tests/GNU-Hello.xml'
hello_selections = os.path.realpath(os.path.join(os.path.dirname(__file__), 'selections.xml'))
local_bad_version = os.path.realpath(os.path.join(os.path.dirname(__file__), 'bad-version.xml'))
local_hello_path = os.path.realpath(os.path.join(os.path.dirname(__file__), 'hello2', 'hello2.xml'))
local_cprog_path = os.path.realpath(os.path.join(os.path.dirname(__file__), 'cprog', 'cprog.xml'))

compile_bin = os.path.abspath('0compile-coverage')
assert os.path.exists(compile_bin)

if 'DISPLAY' in os.environ:
	del os.environ['DISPLAY']

# Ensure it's cached now, to avoid extra output during the tests
if subprocess.call(['0launch', '--source', '-vc', '--download-only', hello_uri]):
	raise Exception("Failed to download hello world test program")

def compile(*args, **kwargs):
	run(*([compile_bin] + list(args)), **kwargs)

def run(*args, **kwargs):
	child = subprocess.Popen(args, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
	got, unused = child.communicate()

	expected = kwargs.get('expect', '')
	if expected:
		if expected.lower() not in got.lower():
			raise Exception("Expected '%s', got '%s'" % (expected, got))
	elif got:
		raise Exception("Expected nothing, got '%s'" % got)

class TestCompile(unittest.TestCase):
	def setUp(self):
		os.chdir('/')
		self.tmpdir = tempfile.mkdtemp(prefix = '0compile-test-')
		self.hello_dir = os.path.join(self.tmpdir, 'hello')
	
	def tearDown(self):
		ro_rmtree(self.tmpdir)

	def testBadCommand(self):
		compile('foo', expect = 'usage: 0compile')
		compile('setup', hello_uri, self.tmpdir, expect = 'already exists')
		os.chdir(self.tmpdir)
		compile('setup', expect = 'Run 0compile from a directory containing')
		compile('build', expect = 'Run 0compile from a directory containing')
		compile('publish', expect = 'Run 0compile from a directory containing')

	def testCompileNoDir(self):
		os.chdir(self.tmpdir)
		compile('setup', hello_uri, expect = 'Created directory')
		os.chdir('GNU-Hello')

	def testCompile(self):
		compile('setup', hello_uri, self.hello_dir, expect = 'Created directory')
		os.chdir(self.hello_dir)

		compile('build', expect = 'Executing: "$SRCDIR/configure"')

		target_dir = 'gnu-hello-%s' % support.get_arch_name().lower()
		archive_stem = 'gnu-hello-%s-1.3' % support.get_arch_name().lower()
		assert os.path.isdir(target_dir), '%s not a directory' % target_dir

		run('%s/bin/hello' % target_dir, expect = 'Hello, world!')
		run('0launch', '%s/0install/GNU-Hello.xml' % target_dir, expect = 'Hello, world!')
		compile('publish', 'http://localhost/downloads', expect = "Now upload '%s.tar.bz2'" % archive_stem)
	
	def testLocal(self):
		compile('setup', local_hello_path, self.hello_dir, expect = 'Created directory')
		os.chdir(self.hello_dir)
		compile('build', expect = 'Executing: ls -l')
		target_dir = 'hello2-%s' % support.get_arch_name().lower()
		assert os.path.isdir(target_dir), '%s not a directory' % target_dir

		run('0launch', '%s/0install/hello2.xml' % target_dir, expect = 'ROX-Lib')
	
	def testBadVersion(self):
		compile('setup', local_bad_version, self.hello_dir, expect = 'Created directory')
		os.chdir(self.hello_dir)
		compile('build', expect = 'hello2-0.1 requires 0compile >= 300000')

	def testCopySrc(self):
		comp_dir = os.path.join(self.tmpdir, 'cprog')
		compile('setup', local_cprog_path, comp_dir, expect = 'Created directory')
		os.chdir(comp_dir)
		compile('diff', expect = "No local src directory to diff against")
		compile('diff', 'foo', expect = 'usage')
		compile('copy-src', 'foo', expect = 'usage')
		compile('copy-src', expect = 'Copied as')
		compile('copy-src', expect = "Directory '")

		# 'src' exists, but no changes
		compile('diff')
		compile('--verbose', 'build', expect = 'Hello from C')
		target_dir = 'cprog-%s' % support.get_arch_name().lower()
		patch_file = os.path.join(target_dir, '0install/from-0.1.patch')
		assert not os.path.exists(patch_file)

		# 'src' contains a change
		prog = file('src/main.c').read()
		prog = prog.replace('Hello', 'Goodbye')
		stream = file('src/main.c', 'w')
		stream.write(prog)
		stream.close()
		compile('diff', expect = 'diff')
		shutil.rmtree('build')
		compile('build', expect = 'Goodbye from C')
		assert os.path.exists(patch_file)

		# Test dup-src's unlinking while we're here
		compile('build', expect = 'Goodbye from C')

		# 'src' contains an error
		stream = file('src/main.c', 'w')
		stream.write('this is not valid C!')
		stream.close()
		shutil.rmtree('build')
		compile('build', expect = 'Build failed')
		assert os.path.exists('build/build-failure.log')

		# 'src' does not exist
		shutil.rmtree('src')
		shutil.rmtree('build')
		compile('build', expect = 'Hello from C')
		assert not os.path.exists(patch_file)

	def testInlcudeDeps(self):
		compile('setup', hello_uri, self.hello_dir, expect = 'Created directory')
		os.chdir(self.hello_dir)
		os.unlink('0compile.properties')
		compile('setup', hello_uri, '.')
		compile('include-deps', expect = 'Copied 1 depend')
		compile('include-deps', expect = 'Copied 0 depend')

	def testSetup(self):
		compile('setup', hello_selections, self.hello_dir,
			expect = 'Created directory')
		compile('setup', hello_selections, self.hello_dir,
			expect = "Directory '")
		compile('setup', hello_selections, '.', 'foo',
			expect = "usage")
		os.chdir(self.hello_dir)
		compile('setup', expect = "Selections are fixed")

suite = unittest.makeSuite(TestCompile)
if __name__ == '__main__':
	sys.argv.append('-v')
	unittest.main()
