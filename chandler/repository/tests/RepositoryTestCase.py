"""
A base class for repository testing
"""
__revision__  = "$Revision$"
__date__      = "$Date$"
__copyright__ = "Copyright (c) 2003 Open Source Applications Foundation"
__license__   = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

from unittest import TestCase
import logging, os, sys

from repository.persistence.XMLRepository import XMLRepository
from repository.util.Path import Path

class RepositoryTestCase(TestCase):

    def setUp(self, ramdb=True):
        self.rootdir = os.environ['CHANDLERHOME']
        handler = logging.FileHandler(os.path.join(self.rootdir,'chandler','chandler.log'))
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        handler.setFormatter(formatter)
        root = logging.getLogger()
        root.addHandler(handler)

        self.ramdb = ramdb
        self.testdir = os.path.join(self.rootdir, 'chandler', 'repository',
                                    'tests')
        self.rep = XMLRepository(os.path.join(self.testdir, '__repository__'))
        self.rep.create(ramdb=self.ramdb)
        schemaPack = os.path.join(self.rootdir, 'chandler', 'repository',
                                  'packs', 'schema.pack')
        self.rep.loadPack(schemaPack)
        self.rep.commit()

    def tearDown(self):
        self.rep.close()
        if not self.ramdb:
            self.rep.delete()

    def _reopenRepository(self):
        self.rep.commit()

        if self.ramdb:
            self.rep.closeView()
            self.rep.openView()
        else:
            self.rep.close()
            self.rep = XMLRepository(os.path.join(self.testdir,
                                                  '__repository__'))
            self.rep.open()

    def _find(self, path):
        return self.rep.findPath(path)

    _KIND_KIND = Path("//Schema/Core/Kind")
    _ITEM_KIND = Path("//Schema/Core/Item")

    # Repository specific assertions
    def assertIsRoot(self, item):
        self.assert_(item in self.rep.getRoots())

    def assertItemPathEqual(self, item, string):
        self.assertEqual(str(item.itsPath), string)
