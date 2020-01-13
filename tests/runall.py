#!/usr/bin/env python3
import unittest, os, sys, tempfile, shutil, atexit

my_dir = os.path.abspath(os.path.dirname(sys.argv[0]))

coverdir = tempfile.mkdtemp(prefix='0compile-coverage-')
atexit.register(shutil.rmtree, coverdir)

os.environ["COVERAGE_FILE"] = os.path.join(coverdir, 'coverage')

try:
	import coverage
	coverage.erase()
except ImportError:
	coverage = None
	print("Coverage module not found. Skipping coverage report.")

sys.argv.append('-v')

suite_names = [f[:-3] for f in os.listdir(my_dir)
		if f.startswith('test') and f.endswith('.py')]
suite_names.sort()

alltests = unittest.TestSuite()

for name in suite_names:
	m = __import__(name, globals(), locals(), [])
	alltests.addTest(m.suite)

a = unittest.TextTestRunner(verbosity=2).run(alltests)

print("\nResult", a)
if not a.wasSuccessful():
	sys.exit(1)

if coverage:
	coverage.the_coverage.collect()
	all_sources = []
	def incl(d):
		for x in os.listdir(d):
			if x.endswith('.py'):
				all_sources.append(os.path.join(d, x))
	incl(os.path.join(my_dir, '..'))
	coverage.report(all_sources)
