import sys
import os


if __name__ == '__main__':
    sys.path.insert(0, os.sep.join(
        os.path.dirname(__file__).split(os.sep)[:-1]))

    import testhttp
    testhttp.cmd()
