# this is a test plugin im writing to see how to create custome plugins.
# this plugin in particulare check to see if a value is equal to blue.

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type




def is_blue(string):

  if string in ['blue','test']:
    return True
  else:
    return False  

# Every 'Test' type plugin must implement this class and function: "TestModule" and "tests()"
class TestModule:
    ''' Ansible blue test '''
    # 'blue' is the name of the plugin, and how it will be referenced.
    def tests(self):
        return {
            'blue': is_blue,
        }
