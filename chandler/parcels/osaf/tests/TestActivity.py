import unittest

if __name__ == "__main__":
    from util.test_finder import ScanningLoader

    unittest.main(module=None, testLoader = ScanningLoader(),
                  argv=["unittest", "osaf.activity.test_suite"])

