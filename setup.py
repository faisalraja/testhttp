from setuptools import setup

setup(name='testhttp',
      version='0.1',
      description='HTTP testing tool',
      url='http://github.com/faisalraja/testhttp',
      author='Faisal Raja',
      author_email='support@altlimit.com',
      license='MIT',
      packages=['testhttp'],
      install_requires=['requests'],
      keywords='http test api',
      zip_safe=False,
      entry_points={
          'console_scripts': ['testhttp = testhttp:cmd']
      }
      )
