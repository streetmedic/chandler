"""
Class association tests for Parcel Loader
"""
__revision__  = "$Revision$"
__date__      = "$Date$"
__copyright__ = "Copyright (c) 2003 Open Source Applications Foundation"
__license__   = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

import ParcelLoaderTestCase, os, sys, unittest

import application

class ClassesTestCase(ParcelLoaderTestCase.ParcelLoaderTestCase):

    def testClasses(self):

        """
        Test to ensure class associations are handled properly
        """
        sys.path.append(os.path.join(self.testdir, 'testparcels'))
        self.manager.path.append(os.path.join(self.testdir, 'testparcels'))
        self.loadParcel("http://testparcels.org/sub")
        self.rep.commit()
        # PrintItem("//parcels", self.rep)
        itemSuper = self.rep.findPath("//parcels/classes/super/itemSuper")
        itemSub = self.rep.findPath("//parcels/classes/sub/itemSub")
        self.assert_(itemSuper.__dict__.has_key('initCalled'))
        self.assertEqual(itemSuper.linksTo, itemSub)
        self.assertEqual(itemSub.linkedFrom, itemSuper)
        # self.assert_(itemSub.__dict__.has_key('initCalled'))

if __name__ == "__main__":
    unittest.main()
