
__revision__  = "$Revision$"
__date__      = "$Date$"
__copyright__ = "Copyright (c) 2002 Open Source Applications Foundation"
__license__   = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

from repository.item.Item import Item
from repository.item.ItemRef import RefDict
from repository.schema.Kind import Kind


class Attribute(Item):
    
    def __init__(self, name, parent, kind):

        super(Attribute, self).__init__(name, parent, kind)
        self._status |= Item.SCHEMA | Item.PINNED

    def _fillItem(self, name, parent, kind, **kwds):

        super(Attribute, self)._fillItem(name, parent, kind, **kwds)
        self._status |= Item.SCHEMA | Item.PINNED
        
    def hasAspect(self, name):

        return self.hasAttributeValue(name)

    def getAspect(self, name, **kwds):

        if self.hasAttributeValue(name):
            return self.getAttributeValue(name)

        if self.hasAttributeValue('superAttribute'):
            return self.getAttributeValue('superAttribute').getAspect(name,
                                                                      **kwds)

        if self._kind is not None:
            aspectAttr = self._kind.getAttribute(name)
            if aspectAttr.hasAttributeValue('defaultValue'):
                return aspectAttr.getAttributeValue('defaultValue')
        
        return kwds.get('default', None)

    def _walk(self, path, callable, **kwds):

        l = len(path)
        
        if path[0] == '//':
            if l == 1:
                return self
            roots = self.getAttributeValue('roots', default=Item.Nil,
                                           _attrDict=self._values)
            if roots is Item.Nil:
                root = None
            else:
                root = roots.get(path[1], None)
            index = 1

        elif path[0] == '/':
            root = self.getAttributeValue('root', default=None,
                                          _attrDict=self._values)
            index = 0

        root = callable(self, path[index], root, **kwds)

        if root is not None:
            index += 1
            if index == l:
                return root
            return root.walk(path, callable, index, **kwds)

        return None
