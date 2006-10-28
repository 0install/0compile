#!/usr/bin/env python2.3
import sys, tempfile, os, shutil, imp, tempfile, popen2
from StringIO import StringIO
import unittest

hello_uri = 'http://0install.net/tests/GNU-Hello.xml'

compile_bin = os.path.abspath('../0compile')
assert os.path.exists(compile_bin)

def compile(*args, **kwargs):
	run(*([compile_bin] + list(args)), **kwargs)

def run(*args, **kwargs):
	cout, cin = popen2.popen4(args)
	cin.close()
	got = cout.read()
	cout.close()

	expected = kwargs.get('expect', '')
	if expected:
		if expected not in got:
			raise Exception("Expected '%s', got '%s'" % (expected, got))
	elif got:
		raise Exception("Expected nothing, got '%s'" % got)

class TestCompile(unittest.TestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp(prefix = '0compile-test-')
		self.hello_dir = os.path.join(self.tmpdir, 'hello')
	
	def tearDown(self):
		shutil.rmtree(self.tmpdir)

	def testBadCommand(self):
		compile('foo', '--no-prompt', expect = 'usage: 0compile')
		compile('setup', '--no-prompt', hello_uri, self.tmpdir, expect = 'already exists')
		os.chdir(self.tmpdir)
		compile('setup', expect = 'Run 0compile from a directory containing')
		compile('build', expect = 'Run 0compile from a directory containing')
		compile('publish', expect = 'Run 0compile from a directory containing')

	def testCompileNoDir(self):
		os.chdir(self.tmpdir)
		compile('setup', '--no-prompt', hello_uri)
		os.chdir('GNU-Hello')
		compile('setup', '--no-prompt')

	def testCompile(self):
		compile('setup', '--no-prompt', hello_uri, self.hello_dir)
		os.chdir(self.hello_dir)
		compile('setup', '--no-prompt')

		compile('build', expect = 'Executing: "$SRCDIR/configure"')
		run('gnu-hello-1.3/bin/hello', expect = 'Hello, world!')
		run('0launch', 'gnu-hello-1.3/0install/GNU-Hello.xml', expect = 'Hello, world!')
		compile('publish', 'http://localhost/downloads', expect = "Now upload 'gnu-hello-1.3.tar.bz2'")

suite = unittest.makeSuite(TestCompile)
if __name__ == '__main__':
	sys.argv.append('-v')
	unittest.main()
